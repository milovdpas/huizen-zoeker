from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# Many-to-many: which cities each recipient wants notifications for.
recipient_cities = Table(
    "recipient_cities",
    Base.metadata,
    Column(
        "recipient_id",
        Integer,
        ForeignKey("email_recipients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "city_id",
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class House(Base):
    __tablename__ = "houses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    address_raw = Column(String(500), nullable=False)
    address_normalized = Column(String(500), nullable=False, index=True)
    city = Column(String(100))
    price_cents = Column(Integer)
    source = Column(String(64), nullable=False)
    source_url = Column(String(1000), nullable=False)
    raw_title = Column(String(500))
    # 'rent' | 'buy' — the same physical property can exist as both (they get
    # distinct source_urls). Dedup is by source_url (see 0002); no DB-level
    # uniqueness on address_normalized, which collides for street-only sites.
    listing_type = Column(String(8), nullable=False, default="rent")
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow)


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)  # always 1 — singleton row
    max_price_cents = Column(Integer, nullable=False, default=150000)  # €1500.00
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    # Canonical lowercase form, admin-editable (sites disagree on slugs).
    slug = Column(String(100), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    scrapers = relationship(
        "CityScraper", back_populates="city", cascade="all, delete-orphan"
    )
    recipients = relationship(
        "EmailRecipient", secondary=recipient_cities, back_populates="cities"
    )


class CityScraper(Base):
    """Per-(city, scraper, listing_type) enablement + optional URL override.

    Only listing types in a scraper's SUPPORTED_TYPES get rows.
    """

    __tablename__ = "city_scrapers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_id = Column(
        Integer, ForeignKey("cities.id", ondelete="CASCADE"), nullable=False
    )
    scraper_key = Column(String(64), nullable=False)
    listing_type = Column(String(8), nullable=False)  # 'rent' | 'buy'
    enabled = Column(Boolean, nullable=False, default=False)
    custom_url = Column(String(1000))  # overrides the templated URL when set

    city = relationship("City", back_populates="scrapers")

    __table_args__ = (
        UniqueConstraint(
            "city_id", "scraper_key", "listing_type", name="uq_city_scraper_type"
        ),
    )


class ScraperConfig(Base):
    """Admin-editable capability flags per scraper, overriding the class-level
    SUPPORTED_TYPES defaults. Controls which listing types appear in the city
    matrix and which jobs the runner will run for this scraper.
    """

    __tablename__ = "scraper_configs"

    scraper_key = Column(String(64), primary_key=True)
    supports_rent = Column(Boolean, nullable=False, default=True)
    supports_buy = Column(Boolean, nullable=False, default=False)


class EmailRecipient(Base):
    __tablename__ = "email_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    wants_rent = Column(Boolean, nullable=False, default=True)
    max_rent_cents = Column(Integer)  # NULL/0 = no cap
    wants_buy = Column(Boolean, nullable=False, default=False)
    max_buy_cents = Column(Integer)  # NULL/0 = no cap
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    cities = relationship(
        "City", secondary=recipient_cities, back_populates="recipients"
    )


class Notification(Base):
    """Per-recipient send log; existence of a row = 'already sent'.

    Replaces House.notified, which couldn't express 'sent to A, not B'.
    """

    __tablename__ = "notifications"

    house_id = Column(
        BigInteger,
        ForeignKey("houses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    recipient_id = Column(
        Integer,
        ForeignKey("email_recipients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False)  # scraper_key
    city = Column(String(100))
    listing_type = Column(String(8))
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    status = Column(String(16), nullable=False, default="running")  # running | ok | failed
    listings_found = Column(Integer, nullable=False, default=0)
    new_listings = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
