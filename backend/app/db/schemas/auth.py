"""
backend/app/db/schemas/auth.py

인증 관련 Pydantic 스키마.
"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    assigned_unit: str | None = None

    model_config = {"from_attributes": True}
