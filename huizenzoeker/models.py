from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class House(Base):
    __tablename__ = "houses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    address_raw = Column(String(500), nullable=False)
    address_normalized = Column(String(500), nullable=False, unique=True, index=True)
    city = Column(String(100))
    price_cents = Column(Integer)
    source = Column(String(64), nullable=False)
    source_url = Column(String(1000), nullable=False)
    raw_title = Column(String(500))
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    notified = Column(Boolean, nullable=False, default=False)


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)  # always 1 — singleton row
    max_price_cents = Column(Integer, nullable=False, default=150000)  # €1500.00
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailRecipient(Base):
    __tablename__ = "email_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    status = Column(String(16), nullable=False, default="running")  # running | ok | failed
    listings_found = Column(Integer, nullable=False, default=0)
    new_listings = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
