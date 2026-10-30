"""
backend/app/db/types.py

DB 방언에 따라 달라지는 컬럼 타입.

운영(PostgreSQL)에서는 JSONB, 그 외(SQLite 테스트 등)에서는 일반 JSON 으로 컴파일된다.
"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSON().with_variant(JSONB(), "postgresql")
