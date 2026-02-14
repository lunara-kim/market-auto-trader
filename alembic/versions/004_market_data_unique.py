"""market_data unique constraint

Revision ID: 004
Revises: 003
Create Date: 2026-02-14
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """market_data 테이블에 unique constraint 추가 (stock_code + date)"""
    op.create_unique_constraint(
        "uq_market_data_stock_code_date",
        "market_data",
        ["stock_code", "date"],
    )


def downgrade() -> None:
    """unique constraint 제거"""
    op.drop_constraint(
        "uq_market_data_stock_code_date",
        "market_data",
        type_="unique",
    )
