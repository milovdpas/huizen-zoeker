"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-04 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "houses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("address_raw", sa.String(500), nullable=False),
        sa.Column("address_normalized", sa.String(500), nullable=False),
        sa.Column("city", sa.String(100)),
        sa.Column("price_cents", sa.Integer()),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("raw_title", sa.String(500)),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("address_normalized", name="uq_houses_address_normalized"),
    )
    op.create_index("ix_houses_address_normalized", "houses", ["address_normalized"])
    op.create_index("ix_houses_first_seen", "houses", ["first_seen"])

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_price_cents", sa.Integer(), nullable=False, server_default="150000"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        "INSERT INTO settings (id, max_price_cents, updated_at) "
        "VALUES (1, 150000, UTC_TIMESTAMP())"
    )

    op.create_table(
        "email_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_email_recipients_email"),
    )

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("listings_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_listings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_scrape_runs_started_at", "scrape_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_scrape_runs_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")
    op.drop_table("email_recipients")
    op.drop_table("settings")
    op.drop_index("ix_houses_first_seen", table_name="houses")
    op.drop_index("ix_houses_address_normalized", table_name="houses")
    op.drop_table("houses")
