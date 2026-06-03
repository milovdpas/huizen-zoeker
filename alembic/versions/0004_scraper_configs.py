"""admin-editable per-scraper supported listing types

Moves the hardcoded SUPPORTED_TYPES out of code into a scraper_configs table
so an admin can toggle rent/buy support per scraper from the UI. Seeds each
known scraper with its current class default.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-04 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# (scraper_key, supports_rent, supports_buy) — current class SUPPORTED_TYPES.
_SEED = [
    ("directwonen", 1, 1),
    ("krabben", 1, 1),
    ("funda", 1, 1),
    ("rncwonen", 1, 0),
    ("easyleasewonen", 1, 0),
    ("gapph", 1, 0),
    ("deleygraaf", 1, 1),
]


def upgrade() -> None:
    op.create_table(
        "scraper_configs",
        sa.Column("scraper_key", sa.String(64), primary_key=True),
        sa.Column("supports_rent", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supports_buy", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    for key, rent, buy in _SEED:
        op.execute(
            "INSERT INTO scraper_configs (scraper_key, supports_rent, supports_buy) "
            f"VALUES ('{key}', {rent}, {buy})"
        )


def downgrade() -> None:
    op.drop_table("scraper_configs")
