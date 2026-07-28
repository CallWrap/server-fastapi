"""분석 결과 저장 — analysis_results

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26

★ 규리와 공유. AnalysisResult(ai/schemas.py)를 저장하는 테이블 (#11).

result JSONB가 진실의 원본. type/category/grade는 대시보드 필터·집계용 승격 컬럼.
콜당 1건(call_id UNIQUE). 소분류·요약·confidence는 result 안에 둔다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # 콜당 분석 1건
        ),
        # AnalysisResult 전체. 계약이 바뀌어도 형태를 흡수한다.
        sa.Column("result", postgresql.JSONB(), nullable=False),
        # result에서 파생한 승격 컬럼 (대시보드 조회용). 부분 실패 시 NULL.
        sa.Column("consultation_type", sa.String(), nullable=True),
        sa.Column("consultation_category", sa.String(), nullable=True),
        sa.Column("grade", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_analysis_grade", "analysis_results", ["grade"])
    op.create_index("idx_analysis_type", "analysis_results", ["consultation_type"])


def downgrade() -> None:
    op.drop_index("idx_analysis_type", table_name="analysis_results")
    op.drop_index("idx_analysis_grade", table_name="analysis_results")
    op.drop_table("analysis_results")
