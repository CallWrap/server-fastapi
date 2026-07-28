"""초기 스키마 — calls, quality_check_results

Revision ID: 0001
Revises:
Create Date: 2026-07-17

★ 규리와 공유. 이 위에 리비전을 쌓을 때 down_revision = "0001"부터 시작한다.

이 파일은 autogenerate가 아니라 손으로 작성했다 (스캐폴딩 시점에 DB가 아직 없었음).
다음 리비전부터는 `uv run alembic revision --autogenerate -m "..."`를 쓴다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("audio_path", sa.String(), nullable=False),
        # status는 VARCHAR다. 진실은 callwrap_api.state.CallStatus.
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # 검토 큐가 "NEEDS_HUMAN_REVIEW인 콜 목록"을 자주 조회한다.
    op.create_index("idx_calls_status", "calls", ["status"])

    op.create_table(
        "quality_check_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_name", sa.String(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("higher_is_better", sa.Boolean(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        # 체크마다 키가 다르므로 JSONB. details->>'sample_size'로 조회 가능.
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("retry_iteration", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_check_call", "quality_check_results", ["call_id", "retry_iteration"]
    )


def downgrade() -> None:
    op.drop_index("idx_check_call", table_name="quality_check_results")
    op.drop_table("quality_check_results")
    op.drop_index("idx_calls_status", table_name="calls")
    op.drop_table("calls")
