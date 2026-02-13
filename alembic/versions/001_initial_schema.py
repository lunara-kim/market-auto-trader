"""초기 스키마: portfolios, orders, market_data, signals

Revision ID: 001
Revises:
Create Date: 2026-02-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── portfolios ──
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_no", sa.String(50), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("profit_loss", sa.Float(), server_default="0.0"),
        sa.Column("profit_loss_rate", sa.Float(), server_default="0.0"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_portfolios_id", "portfolios", ["id"])

    # ── orders ──
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id"),
            nullable=True,
        ),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=True),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("order_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="pending", nullable=False
        ),
        sa.Column("executed_price", sa.Float(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_orders_id", "orders", ["id"])

    # ── market_data ──
    op.create_table(
        "market_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_market_data_id", "market_data", ["id"])
    op.create_index("ix_market_data_stock_code", "market_data", ["stock_code"])
    op.create_index("ix_market_data_date", "market_data", ["date"])

    # ── signals ──
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("signal_type", sa.String(10), nullable=False),
        sa.Column("strength", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("strategy_name", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "is_executed", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_signals_id", "signals", ["id"])


def downgrade() -> None:
    op.drop_table("signals")
    op.drop_table("market_data")
    op.drop_table("orders")
    op.drop_table("portfolios")
