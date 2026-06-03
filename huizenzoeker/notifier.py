import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import settings
from .normalize import cents_to_eur_str
from .models import House


logger = logging.getLogger(__name__)


_env = Environment(
    loader=FileSystemLoader("huizenzoeker/templates"),
    autoescape=select_autoescape(["html"]),
)


def _render_email(house: House) -> str:
    tpl = _env.get_template("email_notification.html")
    return tpl.render(
        house=house,
        price_str=cents_to_eur_str(house.price_cents),
        city=house.city or "",
    )


def _build_message(house: House, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    price_str = cents_to_eur_str(house.price_cents)
    city = house.city or "?"
    msg["Subject"] = f"Nieuwe huurwoning {city} ({price_str}) gevonden"
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)

    text_body = (
        f"Nieuwe huurwoning gevonden in {city}.\n\n"
        f"Adres: {house.address_raw}\n"
        f"Prijs: {price_str}\n"
        f"Bron: {house.source}\n"
        f"Link: {house.source_url}\n"
    )
    msg.set_content(text_body)
    msg.add_alternative(_render_email(house), subtype="html")
    return msg


def send_listing_notification(house: House, recipients: Iterable[str]) -> Optional[str]:
    """Send an email for a single new listing.

    Returns None on success, or an error string on failure.
    """
    rcpts = [r for r in recipients if r and r.strip()]
    if not rcpts:
        logger.info("No recipients configured — skipping email for house id=%s", house.id)
        return "no recipients"

    if not settings.smtp_host:
        logger.warning("SMTP_HOST not set — skipping email")
        return "smtp not configured"

    msg = _build_message(house, rcpts)

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        logger.info("Sent notification for %s to %s", house.address_raw, rcpts)
        return None
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to send notification for %s", house.address_raw)
        return str(e)
