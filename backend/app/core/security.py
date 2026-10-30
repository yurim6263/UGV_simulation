"""
backend/app/core/security.py

비밀번호 해시 + JWT 발급/검증 + FastAPI 인증 의존성.

공개 API (다른 모듈이 import 하는 이름):
    hash_password, verify_password
    create_access_token(subject, role, unit=None)
    TokenPayload                — 검증된 JWT 클레임 (sub, role, unit)
    RequireJwt                  — Annotated 의존성. 엔드포인트에서 `user: CurrentUser` 로 사용
    _decode_token(token)        — WebSocket 처럼 헤더를 쓸 수 없는 곳에서 직접 호출
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except ValueError:
        # 해시 형식이 깨진 레코드 — 인증 실패로 취급
        return False


class TokenPayload(BaseModel):
    sub: str                 # users.id (문자열)
    role: str | None = None  # commander | operator
    unit: str | None = None  # 통제관 담당 제대 (예: "1제대")


def _secret() -> str:
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY 가 설정되지 않았습니다. backend/.env 를 확인하세요.")
    return settings.jwt_secret_key


def create_access_token(subject: str, role: str, unit: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims: dict = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    if unit:
        claims["unit"] = unit
    return jwt.encode(claims, _secret(), algorithm=settings.jwt_algorithm)


def _decode_token(token: str | None) -> TokenPayload:
    """JWT 검증. 토큰이 없거나 유효하지 않으면 예외를 던진다."""
    if not token:
        raise ValueError("token missing")
    try:
        data = jwt.decode(token, _secret(), algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("invalid token") from exc
    sub = data.get("sub")
    if not sub:
        raise ValueError("token has no subject")
    return TokenPayload(sub=str(sub), role=data.get("role"), unit=data.get("unit"))


def _get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenPayload:
    try:
        return _decode_token(credentials.credentials if credentials else None)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요하거나 토큰이 유효하지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


RequireJwt = Annotated[TokenPayload, Depends(_get_token_payload)]
