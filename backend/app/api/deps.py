"""
backend/app/api/deps.py

공통 FastAPI 의존성 재수출.
엔드포인트에서 단일 임포트로 사용:
    from app.api.deps import DBSession, CurrentUser, require_roles

역할 종류:
    commander — 실행 제어, 임무 생성/수정
    operator  — 조회 및 제한된 조작
"""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireJwt, TokenPayload
from app.db.session import get_db

DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = RequireJwt


def require_roles(*roles: str):
    """지정된 역할 중 하나를 가진 사용자만 허용하는 의존성 팩토리.

    사용 예:
        @router.post("", dependencies=[Depends(require_roles("commander"))])
    """
    def _check(user: CurrentUser) -> TokenPayload:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 작업은 {'/'.join(roles)} 역할이 필요합니다.",
            )
        return user
    return _check


def echelon_of(user: TokenPayload) -> int:
    """통제관의 담당 제대 번호. 토큰의 unit 클레임("1제대")에서 읽는다.

    예전에는 user.sub(DB id)의 마지막 자리를 제대 번호로 써서 user1(id=2)이 2제대로 잡혔다.
    """
    m = re.match(r"\s*(\d+)", user.unit or "")
    if not m:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="담당 제대가 지정되지 않은 계정입니다.",
        )
    return int(m.group(1))
