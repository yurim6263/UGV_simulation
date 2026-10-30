"""
backend/app/services/auth_service.py

사용자 인증 서비스.
DB에서 사용자 조회 → 비밀번호 검증 → JWT 발급.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.db.models.user import User


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def authenticate(self, username: str, password: str) -> str | None:
        """인증 성공 시 access_token 반환, 실패 시 None."""
        result = await self.db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            return None
        return create_access_token(
            subject=str(user.id), role=user.role, unit=user.assigned_unit
        )

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self.db.get(User, user_id)
