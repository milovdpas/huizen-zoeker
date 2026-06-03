"""dedup by source_url, not address

Some sources (directwonen) only show street-level addresses with no house
number, so address_normalized collides between distinct listings on the same
street. Switch the primary dedup key to source_url; keep the address index
for cross-site dedup of fully-specified addresses.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-04 00:00:00
"""
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_houses_address_normalized", "houses", type_="unique")
    # Prefix index — VARCHAR(1000) * utf8mb4 exceeds MySQL's 3072-byte key limit
    op.create_index(
        "ix_houses_source_url", "houses", ["source_url"], mysql_length=255
    )


def downgrade() -> None:
    op.drop_index("ix_houses_source_url", table_name="houses")
    op.create_unique_constraint(
        "uq_houses_address_normalized", "houses", ["address_normalized"]
    )
