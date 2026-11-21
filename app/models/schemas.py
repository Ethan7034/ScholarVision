"""Pydantic schemas: the exact shape of every API request and response body."""

from pydantic import BaseModel, ConfigDict
from typing import Any, Optional


class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str


class AnalysisResponse(BaseModel):
    """A finished analysis, embedded as job.result or as a cached result."""

    status: str
    filename: str
    extracted_text_length: int
    analyzed_image: str
    vlm_result: str


class WarningResponse(BaseModel):
    status: str
    message: str
    text_length: int


# ----------------------------------------------------------------------
# Asynchronous job contract
# ----------------------------------------------------------------------
class TaskSubmitResponse(BaseModel):
    """Response to POST /api/analyze: job enqueued, or a direct cache hit."""

    job_id: Optional[str] = None
    status: str  # queued / completed
    filename: str
    cached: bool = False
    result: Optional[dict[str, Any]] = None


class TaskStatusResponse(BaseModel):
    """Response to GET /api/tasks/{job_id}, polled by the frontend."""

    job_id: str
    status: str  # queued / running / completed / failed / cancelled
    filename: Optional[str] = None
    progress: Optional[dict[str, int]] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None


class AuthStatus(BaseModel):
    """Response to GET /auth/me; the SPA uses it to decide whether to open
    the login modal."""

    authenticated: bool
    username: Optional[str] = None
