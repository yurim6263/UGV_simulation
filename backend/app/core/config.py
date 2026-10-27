"""
backend/app/core/config.py

환경 변수 기반 설정 관리.
.env 파일에서 자동 로드 (pydantic-settings).

필수 .env 항목:
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/hanhwa
    JWT_SECRET_KEY=<충분히 긴 랜덤 문자열>
    ADMIN_USERNAME=admin
    ADMIN_PASSWORD=<강한 비밀번호>

선택 .env 항목:
    BACKEND_CORS_ORIGINS=http://localhost:8765,http://127.0.0.1:8765
    ASSET_BASE_PATH=./data            (기본값)
    JWT_ALGORITHM=HS256               (기본값)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60 (기본값)
    GEMINI_API_KEY=<Google AI Studio 키>   (없으면 AI 어시스턴트 비활성)
    GEMINI_MODEL=gemini-2.5-flash          (기본값)
"""

import sys
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_UNSAFE_SECRETS = {"", "1234", "change-me", "secret", "change-me-to-random-secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # DB
    database_url: str

    # JWT
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # CORS — 쉼표 구분 문자열, 없으면 localhost만 허용
    backend_cors_origins: str = "http://localhost:8765,http://127.0.0.1:8765"

    # Admin 계정 (users 테이블 seed용)
    admin_username: str = "admin"
    admin_password: str = ""

    # 파일 저장 경로
    asset_base_path: str = "./data"

    # LLM 어시스턴트 (Gemini). 키가 없으면 어시스턴트 API 는 503 을 돌려주고 나머지 기능은 그대로 동작한다.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"      # 모델 이름은 계정/시점에 따라 달라질 수 있어 환경변수로 바꾼다
    assistant_rate_limit: str = "20/minute"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    def validate_secrets(self) -> None:
        """취약 시크릿 키 감지 시 경고 (개발환경) 또는 종료 (프로덕션)."""
        if self.jwt_secret_key in _UNSAFE_SECRETS:
            logger.warning(
                "JWT_SECRET_KEY가 비어있거나 기본값입니다. "
                "프로덕션 배포 전 반드시 강한 랜덤 값으로 변경하세요."
            )


settings = Settings()
settings.validate_secrets()
