"""Alembic 환경. DB URL과 메타데이터를 앱 설정에서 가져온다.

★ 규리와 공유 — 마이그레이션은 둘 다 만들게 된다. 새 리비전은 반드시
   down_revision을 최신 head에 맞춰서 생성할 것 (여러 head가 생기면 병합이 필요해진다).
   현재 head 확인: uv run alembic heads
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from callwrap_api.db.models import Base
from callwrap_api.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini에 URL을 박지 않고 .env에서 읽는다.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 컬럼 타입 변경도 autogenerate가 잡도록.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
