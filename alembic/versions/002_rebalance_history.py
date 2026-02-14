"""리밸런싱 내역: rebalance_history, rebalance_order_details

Revision ID: 002
Revises: 001
Create Date: 2026-02-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── rebalance_history ──
    op.create_table(
        "rebalance_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("schedule_type", sa.String(20), nullable=True),
        sa.Column("total_equity", sa.Float(), nullable=False),
        sa.Column("cash_before", sa.Float(), nullable=False),
        sa.Column("cash_after", sa.Float(), nullable=False),
        sa.Column("total_orders", sa.Integer(), nullable=False),
        sa.Column("buy_orders_count", sa.Integer(), nullable=False),
        sa.Column("sell_orders_count", sa.Integer(), nullable=False),
        sa.Column("skipped_stocks", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_rebalance_history_id", "rebalance_history", ["id"],
    )

    # ── rebalance_order_details ──
    op.create_table(
        "rebalance_order_details",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "rebalance_id",
            sa.Integer(),
            sa.ForeignKey("rebalance_history.id"),
            nullable=False,
        ),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("target_value_krw", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default="planned",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_rebalance_order_details_id",
        "rebalance_order_details",
        ["id"],
    )


def downgrade() -> None:
    op.drop_table("rebalance_order_details")
    op.drop_table("rebalance_history")
