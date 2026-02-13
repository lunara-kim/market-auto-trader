"""
Alembic 마이그레이션 환경 설정

동기/비동기 두 가지 모드를 지원합니다.
- 오프라인: SQL 스크립트만 생성 (DB 연결 불필요)
- 온라인: 실제 DB에 마이그레이션 적용
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from src.models.schema import Base  # noqa: E402

# Alembic Config 객체
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy MetaData (autogenerate용)
target_metadata = Base.metadata


def get_url() -> str:
    """환경변수에서 DB URL을 가져옴 (동기 드라이버 사용)"""
    url = settings.database_url
    # asyncpg URL이면 동기 드라이버로 변환
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def run_migrations_offline() -> None:
    """
    오프라인 모드: DB 연결 없이 SQL 스크립트를 생성합니다.

    사용법: alembic upgrade head --sql
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    온라인 모드: 실제 DB에 연결하여 마이그레이션을 적용합니다.
    """
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
