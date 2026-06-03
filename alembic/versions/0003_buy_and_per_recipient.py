"""buy support + per-recipient, multi-city preferences

Adds the scalable City catalog, per-(city, scraper, type) enablement
(CityScraper), recipient<->city links, per-recipient rent/buy preferences,
House.listing_type, and a per-recipient notifications log replacing
House.notified. ScrapeRun gains city + listing_type.

Data steps preserve current behavior: all existing houses become rent;
Oss+Berghem are seeded; the single existing recipient keeps the old global
max as its rent cap and is linked to both cities; the (city, scraper) combos
that run today are seeded enabled; already-notified houses are copied into the
notifications log so nobody is re-emailed.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# RNC's Drupal taxonomy URL can't be templated by city — seed it as a custom
# override for both seeded cities (it covered Oss+Berghem combined).
_RNC_LEGACY_URL = (
    "https://www.rncwonen.nl/aanbod"
    "?field_location_taxonomy_target_id%5B%5D=718"
    "&field_location_taxonomy_target_id%5B%5D=712"
    "&range=10"
    "&field_house_type_target_id=All"
    "&field_price_deci_value=5"
)

# (city, scraper) combos that run today — preserve exactly current coverage.
_OSS_SCRAPERS = [
    "directwonen",
    "krabben",
    "funda",
    "rncwonen",
    "easyleasewonen",
    "gapph",
    "deleygraaf",
]
_BERGHEM_SCRAPERS = ["directwonen", "funda", "rncwonen"]


def upgrade() -> None:
    # --- houses.listing_type (backfill 'rent', then enforce NOT NULL) ---
    op.add_column("houses", sa.Column("listing_type", sa.String(8), nullable=True))
    op.execute("UPDATE houses SET listing_type = 'rent'")
    op.alter_column("houses", "listing_type", existing_type=sa.String(8), nullable=False)

    # --- cities catalog ---
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_cities_slug"),
    )
    op.execute(
        "INSERT INTO cities (name, slug, enabled, created_at) VALUES "
        "('Oss', 'oss', 1, UTC_TIMESTAMP()), "
        "('Berghem', 'berghem', 1, UTC_TIMESTAMP())"
    )

    # --- per-(city, scraper, type) enablement ---
    op.create_table(
        "city_scrapers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("scraper_key", sa.String(64), nullable=False),
        sa.Column("listing_type", sa.String(8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("custom_url", sa.String(1000)),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "city_id", "scraper_key", "listing_type", name="uq_city_scraper_type"
        ),
    )

    def _seed_city_scrapers(slug: str, scraper_keys: list[str]) -> None:
        for key in scraper_keys:
            custom = f"'{_RNC_LEGACY_URL}'" if key == "rncwonen" else "NULL"
            op.execute(
                "INSERT INTO city_scrapers "
                "(city_id, scraper_key, listing_type, enabled, custom_url) "
                f"SELECT id, '{key}', 'rent', 1, {custom} FROM cities WHERE slug = '{slug}'"
            )

    _seed_city_scrapers("oss", _OSS_SCRAPERS)
    _seed_city_scrapers("berghem", _BERGHEM_SCRAPERS)

    # --- recipient preferences ---
    op.add_column(
        "email_recipients",
        sa.Column("wants_rent", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("email_recipients", sa.Column("max_rent_cents", sa.Integer(), nullable=True))
    op.add_column(
        "email_recipients",
        sa.Column("wants_buy", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("email_recipients", sa.Column("max_buy_cents", sa.Integer(), nullable=True))
    # Existing recipients keep the old global max as their rent cap.
    op.execute(
        "UPDATE email_recipients "
        "SET max_rent_cents = (SELECT max_price_cents FROM settings WHERE id = 1)"
    )

    # --- recipient <-> city links ---
    op.create_table(
        "recipient_cities",
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["email_recipients.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipient_id", "city_id"),
    )
    # Every existing recipient gets both seeded cities.
    op.execute(
        "INSERT INTO recipient_cities (recipient_id, city_id) "
        "SELECT r.id, c.id FROM email_recipients r CROSS JOIN cities c"
    )

    # --- per-recipient send log (replaces houses.notified) ---
    op.create_table(
        "notifications",
        sa.Column("house_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["house_id"], ["houses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["email_recipients.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("house_id", "recipient_id"),
    )
    # Copy already-notified houses for every recipient so nobody is re-emailed.
    op.execute(
        "INSERT INTO notifications (house_id, recipient_id, sent_at) "
        "SELECT h.id, r.id, UTC_TIMESTAMP() "
        "FROM houses h CROSS JOIN email_recipients r WHERE h.notified = 1"
    )
    op.drop_column("houses", "notified")

    # --- scrape_runs gains per-job dimensions ---
    op.add_column("scrape_runs", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("scrape_runs", sa.Column("listing_type", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("scrape_runs", "listing_type")
    op.drop_column("scrape_runs", "city")

    op.add_column(
        "houses",
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    # Restore notified for any house that had at least one notification.
    op.execute(
        "UPDATE houses SET notified = 1 "
        "WHERE id IN (SELECT DISTINCT house_id FROM notifications)"
    )
    op.drop_table("notifications")
    op.drop_table("recipient_cities")

    op.drop_column("email_recipients", "max_buy_cents")
    op.drop_column("email_recipients", "wants_buy")
    op.drop_column("email_recipients", "max_rent_cents")
    op.drop_column("email_recipients", "wants_rent")

    op.drop_table("city_scrapers")
    op.drop_table("cities")

    op.drop_column("houses", "listing_type")
