"""
Authentication routes.

v1.0 handed a token to the frontend for localStorage and never verified it
server-side, which made the whole login ceremony decorative.

v2.0 uses server-side sessions: a successful login writes the JWT into an
httpOnly cookie, the browser attaches it to every later request, and the
gateway middleware is the single place that checks it. An unauthenticated
visit to a protected page 302s to "/?auth=required", which the SPA turns
into the SYSTEM_AUTH modal.

Authorization: Bearer stays supported so curl and scripts still work.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.security import (
    clear_session_cookie,
    extract_token,
    get_current_user,
    get_password_hash,
    issue_session_cookie,
    revoke_token,
    verify_password,
)
from app.models.database import User, get_db
from app.models.schemas import AuthStatus, Token, UserCreate

router = APIRouter()


@router.post("/register", response_model=dict)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    new_user = User(
        username=user.username,
        hashed_password=get_password_hash(user.password),
    )
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}


@router.post("/login", response_model=Token)
def login(user: UserCreate, response: Response, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    # 核心变化：token 进 httpOnly Cookie（JS 读不到，XSS 拿不走）
    access_token = issue_session_cookie(response, db_user.username)
    return {"access_token": access_token, "token_type": "bearer", "session_mode": "cookie"}


@router.post("/logout", response_model=dict)
async def logout(request: Request, response: Response):
    """Logout = clear the browser cookie AND revoke the session server-side.

    Either step alone is insufficient: revocation covers anyone who copied the
    token, the cookie clear covers the honest browser.
    """
    token = extract_token(request)
    if token:
        await revoke_token(token)
    clear_session_cookie(response)
    return {"message": "Logged out"}


@router.get("/me", response_model=AuthStatus)
def read_me(
    user: User = Depends(get_current_user),
):
    """Session probe for the SPA; a 401 here means "not signed in"."""
    return AuthStatus(authenticated=True, username=user.username)
