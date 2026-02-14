"""알림 규칙: alert_rules

Revision ID: 003
Revises: 002
Create Date: 2026-02-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── alert_rules ──
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(20), nullable=False, index=True),
        sa.Column("stock_name", sa.String(100), nullable=True),
        sa.Column("condition", sa.String(30), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_alert_rules_id", "alert_rules", ["id"])
    op.create_index("ix_alert_rules_stock_code", "alert_rules", ["stock_code"])


def downgrade() -> None:
    op.drop_table("alert_rules")
