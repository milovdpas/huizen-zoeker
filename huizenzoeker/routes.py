from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import desc, select

from .db import session_scope
from .models import EmailRecipient, House, ScrapeRun, Settings
from .normalize import cents_to_eur_str
from .scheduler import trigger_now, trigger_refresh_funda_cookies, trigger_source


_SORTABLE_HOUSE_COLUMNS = {
    "first_seen": House.first_seen,
    "price": House.price_cents,
}


bp = Blueprint("web", __name__)


@bp.app_template_filter("eur")
def eur_filter(cents):
    return cents_to_eur_str(cents)


@bp.app_template_filter("dt")
def dt_filter(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


@bp.route("/")
def houses():
    sort = request.args.get("sort", "first_seen")
    direction = request.args.get("dir", "desc")
    if sort not in _SORTABLE_HOUSE_COLUMNS:
        sort = "first_seen"
    if direction not in {"asc", "desc"}:
        direction = "desc"

    filters = {
        "min_price": (request.args.get("min_price") or "").strip(),
        "max_price": (request.args.get("max_price") or "").strip(),
        "since": (request.args.get("since") or "").strip(),
    }

    stmt = select(House)

    min_price_cents = _eur_to_cents(filters["min_price"])
    max_price_cents = _eur_to_cents(filters["max_price"])
    if min_price_cents is not None:
        stmt = stmt.where(House.price_cents >= min_price_cents)
    if max_price_cents is not None:
        stmt = stmt.where(House.price_cents <= max_price_cents)

    since_dt = _parse_date(filters["since"])
    if since_dt is not None:
        stmt = stmt.where(House.first_seen >= since_dt)

    column = _SORTABLE_HOUSE_COLUMNS[sort]
    # Push NULL prices to the end regardless of direction — otherwise they
    # cluster at the top when sorting price asc and obscure the cheap ones.
    stmt = stmt.order_by(
        column.is_(None),
        column.asc() if direction == "asc" else column.desc(),
    ).limit(200)

    with session_scope() as s:
        rows = s.scalars(stmt).all()
        houses_list = [
            {
                "id": h.id,
                "address_raw": h.address_raw,
                "city": h.city,
                "price_cents": h.price_cents,
                "source": h.source,
                "source_url": h.source_url,
                "first_seen": h.first_seen,
                "last_seen": h.last_seen,
                "notified": h.notified,
            }
            for h in rows
        ]
    return render_template(
        "houses.html",
        houses=houses_list,
        sort=sort,
        direction=direction,
        filters=filters,
        active_filters={k: v for k, v in filters.items() if v},
    )


def _eur_to_cents(value: str):
    if not value:
        return None
    try:
        return int(round(float(value.replace(",", ".")) * 100))
    except ValueError:
        return None


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        action = request.form.get("action")
        with session_scope() as s:
            row = s.get(Settings, 1)
            if row is None:
                row = Settings(id=1, max_price_cents=0)
                s.add(row)

            if action == "save_max_price":
                raw = (request.form.get("max_price") or "").strip()
                try:
                    value_eur = float(raw.replace(",", ".")) if raw else 0
                    row.max_price_cents = int(round(value_eur * 100))
                    row.updated_at = datetime.utcnow()
                    flash("Max prijs opgeslagen.", "success")
                except ValueError:
                    flash("Ongeldige prijs.", "error")

            elif action == "add_email":
                email = (request.form.get("email") or "").strip().lower()
                if "@" not in email or "." not in email:
                    flash("Ongeldig e-mailadres.", "error")
                else:
                    exists = s.scalars(
                        select(EmailRecipient).where(EmailRecipient.email == email)
                    ).first()
                    if exists:
                        flash("E-mail bestaat al.", "error")
                    else:
                        s.add(EmailRecipient(email=email, created_at=datetime.utcnow()))
                        flash(f"{email} toegevoegd.", "success")

            elif action == "delete_email":
                rid = request.form.get("id")
                if rid:
                    obj = s.get(EmailRecipient, int(rid))
                    if obj:
                        s.delete(obj)
                        flash("Verwijderd.", "success")

        return redirect(url_for("web.settings_page"))

    with session_scope() as s:
        row = s.get(Settings, 1)
        max_price_cents = row.max_price_cents if row else 0
        recipients = [
            {"id": r.id, "email": r.email}
            for r in s.scalars(
                select(EmailRecipient).order_by(EmailRecipient.email)
            ).all()
        ]
    return render_template(
        "settings.html",
        max_price_cents=max_price_cents,
        max_price_eur=f"{max_price_cents / 100:.0f}" if max_price_cents else "",
        recipients=recipients,
    )


@bp.route("/runs")
def runs():
    with session_scope() as s:
        rows = s.scalars(
            select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(100)
        ).all()
        runs_list = [
            {
                "id": r.id,
                "source": r.source,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "listings_found": r.listings_found,
                "new_listings": r.new_listings,
                "error_message": r.error_message,
            }
            for r in rows
        ]
    return render_template("runs.html", runs=runs_list)


@bp.route("/run-now", methods=["POST"])
def run_now():
    try:
        trigger_now()
        flash("Scrape gestart op de achtergrond.", "success")
    except Exception as e:  # noqa: BLE001
        flash(f"Kon niet starten: {e}", "error")
    return redirect(url_for("web.runs"))


@bp.route("/refresh-funda-cookies", methods=["POST"])
def refresh_funda_cookies_now():
    try:
        trigger_refresh_funda_cookies()
        flash("Funda-cookies verversen gestart op de achtergrond.", "success")
    except Exception as e:  # noqa: BLE001
        flash(f"Kon niet starten: {e}", "error")
    return redirect(url_for("web.runs"))


@bp.route("/run-source", methods=["POST"])
def run_source_now():
    src = (request.form.get("source") or "").strip()
    if not src:
        flash("Geen bron opgegeven.", "error")
        return redirect(url_for("web.runs"))
    try:
        trigger_source(src)
        flash(f"Scrape van '{src}' gestart op de achtergrond.", "success")
    except Exception as e:  # noqa: BLE001
        flash(f"Kon niet starten: {e}", "error")
    return redirect(url_for("web.runs"))
