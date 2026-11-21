"""
Security layer: JWT issue / verify / revoke, plus session-cookie helpers.

v1.0 only created tokens (create_access_token) and never verified one, so the
token was decorative. v2.0 closes that gap here.

Three design decisions
  1. The token travels in an httpOnly cookie, so page JavaScript cannot read
     it and XSS cannot exfiltrate it. Authorization: Bearer is still accepted
     for curl and scripted debugging.
  2. The payload carries a unique `jti`; logout records that jti in a
     revocation list. Plain JWT is stateless and the server cannot invalidate
     it otherwise -- without this step, logging out only clears the browser
     cookie while anyone holding the old token keeps full access.
  3. SECRET_KEY comes from .env; the source keeps only an insecure dev
     default, because a public repository would leak any real key.
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.store import store
from app.models.database import User, get_db

# 兼容旧代码：仍暴露模块级常量，真实来源是 settings / 环境变量
SECRET_KEY = os.getenv("SECRET_KEY") or settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    to_encode.update(
        {
            "exp": now + timedelta(minutes=minutes),
            "iat": now,
            "jti": uuid.uuid4().hex,  # 供撤销名单定位
        }
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Verify signature and expiry (synchronous; does not check revocation).

    Raises HTTPException(401) on any failure.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的登录凭证",
        )
    if not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证缺少用户标识")
    return payload


def _revoke_key(jti: str) -> str:
    return f"sv:revoked:{jti}"


async def revoke_token(token: str) -> None:
    """Blacklist a token's jti until that token would have expired anyway."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return  # 本来就无效的 token 无需撤销
    exp = payload.get("exp") or 0
    ttl = max(1, int(exp - datetime.now(timezone.utc).timestamp()))
    jti = payload.get("jti")
    if jti:
        await store.set_json(_revoke_key(jti), {"revoked_at": time.time()}, ttl=ttl)
        logger.info(f"🚪 会话已撤销: {payload.get('sub')}")


async def is_token_revoked(token: str) -> bool:
    payload = decode_token(token)
    jti = payload.get("jti")
    if not jti:
        return True  # 无 jti 的旧 token 一律视为不可信
    return (await store.get_json(_revoke_key(jti))) is not None


# ----------------------------------------------------------------------
# Cookie session: issue / clear / extract
# ----------------------------------------------------------------------
def issue_session_cookie(response: Response, username: str) -> str:
    """Mint a token, attach it as an httpOnly cookie, return the token itself."""
    token = create_access_token({"sub": username})
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )
    return token


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME, path="/")


def extract_token(request: Request) -> str | None:
    """Session cookie first, then an Authorization: Bearer header."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        return token
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


async def authenticate_token(token: str | None) -> str | None:
    """Single source of truth for authentication.

    Valid signature plus a clean revocation check returns the username;
    anything else returns None. The gateway middleware and route dependencies
    share this so the two can never drift apart.
    """
    if not token:
        return None
    try:
        payload = decode_token(token)
    except HTTPException:
        return None
    if await is_token_revoked(token):
        return None
    return payload.get("sub")


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials=Depends(bearer_scheme),
) -> User:
    """Route dependency requiring a valid, non-revoked session (else 401).

    Complements the gateway middleware: the middleware turns unauthenticated
    page visits into a 302 redirect, while this dependency answers API calls
    with a 401 JSON body.
    """
    token = extract_token(request) or (credentials.credentials if credentials else None)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    username = await authenticate_token(token)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话无效或已退出")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user
