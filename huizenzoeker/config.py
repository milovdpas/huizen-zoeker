import os
from dataclasses import dataclass


_DEFAULT_SCRAPE_TIMES: tuple[str, ...] = ("09:00", "12:00", "17:00", "20:00")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _scrape_times(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    parsed: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        parts = token.split(":")
        if len(parts) != 2:
            continue
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if 0 <= h <= 23 and 0 <= m <= 59:
            parsed.append(f"{h:02d}:{m:02d}")
    return tuple(parsed) if parsed else default


@dataclass(frozen=True)
class Settings:
    database_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    flask_host: str
    flask_port: int
    flask_secret_key: str
    app_base_url: str
    scrape_times: tuple[str, ...]
    scrape_on_startup: bool
    auto_refresh_funda_cookies: bool
    funda_cookie_refresh_lead_minutes: int
    headless: bool
    scrape_timeout: int
    log_level: str


def _load() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", ""),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=_int("SMTP_PORT", 587),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        smtp_use_tls=_bool("SMTP_USE_TLS", True),
        flask_host=os.getenv("FLASK_HOST", "127.0.0.1"),
        flask_port=_int("FLASK_PORT", 5000),
        flask_secret_key=os.getenv("FLASK_SECRET_KEY", "dev"),
        app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:5000"),
        scrape_times=_scrape_times("SCRAPE_TIMES", _DEFAULT_SCRAPE_TIMES),
        scrape_on_startup=_bool("SCRAPE_ON_STARTUP", True),
        auto_refresh_funda_cookies=_bool("AUTO_REFRESH_FUNDA_COOKIES", True),
        funda_cookie_refresh_lead_minutes=_int("FUNDA_COOKIE_REFRESH_LEAD_MINUTES", 30),
        headless=_bool("HEADLESS", True),
        scrape_timeout=_int("SCRAPE_TIMEOUT", 45),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


settings = _load()
