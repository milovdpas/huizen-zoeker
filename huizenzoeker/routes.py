from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import desc, func, select

from .db import session_scope
from .models import (
    City,
    CityScraper,
    EmailRecipient,
    House,
    Notification,
    ScrapeRun,
    ScraperConfig,
)
from .normalize import cents_to_eur_str, slugify
from .scrapers import SCRAPERS, effective_supported_types
from .scheduler import trigger_now, trigger_refresh_funda_cookies, trigger_source


_SORTABLE_HOUSE_COLUMNS = {
    "first_seen": House.first_seen,
    "price": House.price_cents,
}

_LISTING_TYPE_LABELS = {"rent": "Huur", "buy": "Koop"}


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


@bp.app_template_filter("ltype")
def ltype_filter(value):
    return _LISTING_TYPE_LABELS.get(value, value or "?")


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
        "type": (request.args.get("type") or "").strip(),
    }

    stmt = select(House)

    min_price_cents = _eur_to_cents(filters["min_price"])
    max_price_cents = _eur_to_cents(filters["max_price"])
    if min_price_cents is not None:
        stmt = stmt.where(House.price_cents >= min_price_cents)
    if max_price_cents is not None:
        stmt = stmt.where(House.price_cents <= max_price_cents)
    if filters["type"] in {"rent", "buy"}:
        stmt = stmt.where(House.listing_type == filters["type"])

    since_dt = _parse_date(filters["since"])
    if since_dt is not None:
        stmt = stmt.where(House.first_seen >= since_dt)

    column = _SORTABLE_HOUSE_COLUMNS[sort]
    # Push NULL prices to the end regardless of direction.
    stmt = stmt.order_by(
        column.is_(None),
        column.asc() if direction == "asc" else column.desc(),
    ).limit(200)

    with session_scope() as s:
        rows = s.scalars(stmt).all()
        ids = [h.id for h in rows]
        notif_counts: dict[int, int] = {}
        if ids:
            for hid, cnt in s.execute(
                select(Notification.house_id, func.count())
                .where(Notification.house_id.in_(ids))
                .group_by(Notification.house_id)
            ).all():
                notif_counts[hid] = cnt
        houses_list = [
            {
                "id": h.id,
                "address_raw": h.address_raw,
                "city": h.city,
                "price_cents": h.price_cents,
                "source": h.source,
                "source_url": h.source_url,
                "listing_type": h.listing_type,
                "first_seen": h.first_seen,
                "last_seen": h.last_seen,
                "notif_count": notif_counts.get(h.id, 0),
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


def _recipient_form_prefs():
    """Read the recipient pref fields from the current request form."""
    return {
        "wants_rent": bool(request.form.get("wants_rent")),
        "max_rent_cents": _eur_to_cents((request.form.get("max_rent") or "").strip()),
        "wants_buy": bool(request.form.get("wants_buy")),
        "max_buy_cents": _eur_to_cents((request.form.get("max_buy") or "").strip()),
        "city_ids": [int(x) for x in request.form.getlist("city_ids") if x.isdigit()],
    }


def _apply_recipient(session, recipient: EmailRecipient, prefs: dict) -> None:
    recipient.wants_rent = prefs["wants_rent"]
    recipient.max_rent_cents = prefs["max_rent_cents"]
    recipient.wants_buy = prefs["wants_buy"]
    recipient.max_buy_cents = prefs["max_buy_cents"]
    if prefs["city_ids"]:
        recipient.cities = (
            session.scalars(select(City).where(City.id.in_(prefs["city_ids"]))).all()
        )
    else:
        recipient.cities = []


@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        action = request.form.get("action")
        with session_scope() as s:
            if action == "add_email":
                email = (request.form.get("email") or "").strip().lower()
                if "@" not in email or "." not in email:
                    flash("Ongeldig e-mailadres.", "error")
                elif s.scalars(
                    select(EmailRecipient).where(EmailRecipient.email == email)
                ).first():
                    flash("E-mail bestaat al.", "error")
                else:
                    r = EmailRecipient(email=email, created_at=datetime.utcnow())
                    s.add(r)
                    _apply_recipient(s, r, _recipient_form_prefs())
                    flash(f"{email} toegevoegd.", "success")

            elif action == "edit_email":
                rid = request.form.get("id")
                obj = s.get(EmailRecipient, int(rid)) if rid else None
                if obj:
                    _apply_recipient(s, obj, _recipient_form_prefs())
                    flash(f"{obj.email} bijgewerkt.", "success")

            elif action == "delete_email":
                rid = request.form.get("id")
                obj = s.get(EmailRecipient, int(rid)) if rid else None
                if obj:
                    s.delete(obj)
                    flash("Verwijderd.", "success")

        return redirect(url_for("web.settings_page"))

    with session_scope() as s:
        cities = s.scalars(select(City).order_by(City.name)).all()
        cities_list = [{"id": c.id, "name": c.name, "slug": c.slug} for c in cities]
        recipients = []
        for r in s.scalars(select(EmailRecipient).order_by(EmailRecipient.email)).all():
            recipients.append(
                {
                    "id": r.id,
                    "email": r.email,
                    "wants_rent": r.wants_rent,
                    "max_rent_eur": f"{r.max_rent_cents / 100:.0f}" if r.max_rent_cents else "",
                    "wants_buy": r.wants_buy,
                    "max_buy_eur": f"{r.max_buy_cents / 100:.0f}" if r.max_buy_cents else "",
                    "city_ids": {c.id for c in r.cities},
                }
            )
    return render_template("settings.html", recipients=recipients, cities=cities_list)


@bp.route("/cities", methods=["GET", "POST"])
def cities_page():
    if request.method == "POST":
        action = request.form.get("action")
        with session_scope() as s:
            if action == "add_city":
                name = (request.form.get("name") or "").strip()
                slug = (request.form.get("slug") or "").strip().lower() or slugify(name)
                if not name or not slug:
                    flash("Naam en slug zijn verplicht.", "error")
                elif s.scalars(select(City).where(City.slug == slug)).first():
                    flash(f"Slug '{slug}' bestaat al.", "error")
                else:
                    city = City(name=name, slug=slug, enabled=True, created_at=datetime.utcnow())
                    s.add(city)
                    s.flush()
                    # Pre-create a disabled row for every scraper × supported type.
                    supported = effective_supported_types(s)
                    for key in SCRAPERS:
                        for ltype in sorted(supported.get(key, set())):
                            s.add(
                                CityScraper(
                                    city_id=city.id,
                                    scraper_key=key,
                                    listing_type=ltype,
                                    enabled=False,
                                    custom_url=None,
                                )
                            )
                    flash(f"Stad '{name}' toegevoegd.", "success")

            elif action == "delete_city":
                cid = request.form.get("id")
                city = s.get(City, int(cid)) if cid else None
                if city:
                    s.delete(city)
                    flash(f"Stad '{city.name}' verwijderd.", "success")

            elif action == "toggle_city":
                cid = request.form.get("id")
                city = s.get(City, int(cid)) if cid else None
                if city:
                    city.enabled = not city.enabled
                    flash(
                        f"Stad '{city.name}' {'ingeschakeld' if city.enabled else 'uitgeschakeld'}.",
                        "success",
                    )

            elif action == "save_scrapers":
                cid = request.form.get("id")
                city = s.get(City, int(cid)) if cid else None
                if city:
                    for cs in city.scrapers:
                        cs.enabled = bool(request.form.get(f"enabled_{cs.id}"))
                        custom = (request.form.get(f"custom_url_{cs.id}") or "").strip()
                        cs.custom_url = custom or None
                    flash(f"Scrapers voor '{city.name}' opgeslagen.", "success")

        return redirect(url_for("web.cities_page"))

    with session_scope() as s:
        cities_data = []
        cities = s.scalars(select(City).order_by(City.name)).all()
        supported = effective_supported_types(s)
        # Backfill any missing (scraper, type) rows so the full matrix is always
        # editable — migration-seeded cities only got their historical combos.
        for city in cities:
            existing = {(cs.scraper_key, cs.listing_type) for cs in city.scrapers}
            for key in SCRAPERS:
                for ltype in supported.get(key, set()):
                    if (key, ltype) not in existing:
                        city.scrapers.append(
                            CityScraper(
                                scraper_key=key,
                                listing_type=ltype,
                                enabled=False,
                                custom_url=None,
                            )
                        )
        s.flush()

        for city in cities:
            by_key = {}
            for cs in city.scrapers:
                by_key.setdefault(cs.scraper_key, {})[cs.listing_type] = cs
            scraper_rows = []
            for key, cls in sorted(SCRAPERS.items(), key=lambda kv: kv[1].DISPLAY_NAME):
                types = []
                for ltype in sorted(supported.get(key, set())):
                    cs = by_key.get(key, {}).get(ltype)
                    if cs is None:
                        continue
                    templated = cls.build_url(
                        city_slug=city.slug, city_name=city.name, listing_type=ltype
                    )
                    types.append(
                        {
                            "cs_id": cs.id,
                            "listing_type": ltype,
                            "label": _LISTING_TYPE_LABELS.get(ltype, ltype),
                            "enabled": cs.enabled,
                            "custom_url": cs.custom_url or "",
                            "templated_url": templated,
                            "has_template": ltype in cls.URL_TEMPLATES,
                        }
                    )
                if types:
                    scraper_rows.append(
                        {"key": key, "display_name": cls.DISPLAY_NAME, "types": types}
                    )
            cities_data.append(
                {
                    "id": city.id,
                    "name": city.name,
                    "slug": city.slug,
                    "enabled": city.enabled,
                    "scrapers": scraper_rows,
                }
            )
    return render_template("cities.html", cities=cities_data)


@bp.route("/scrapers", methods=["GET", "POST"])
def scrapers_page():
    if request.method == "POST":
        with session_scope() as s:
            existing = {sc.scraper_key: sc for sc in s.scalars(select(ScraperConfig)).all()}
            for key in SCRAPERS:
                sc = existing.get(key)
                if sc is None:
                    sc = ScraperConfig(scraper_key=key)
                    s.add(sc)
                sc.supports_rent = bool(request.form.get(f"rent_{key}"))
                sc.supports_buy = bool(request.form.get(f"buy_{key}"))
            flash("Scraper-instellingen opgeslagen.", "success")
        return redirect(url_for("web.scrapers_page"))

    with session_scope() as s:
        supported = effective_supported_types(s)
        scrapers_list = []
        for key, cls in sorted(SCRAPERS.items(), key=lambda kv: kv[1].DISPLAY_NAME):
            types = supported.get(key, set())
            scrapers_list.append(
                {
                    "key": key,
                    "display_name": cls.DISPLAY_NAME,
                    "supports_rent": "rent" in types,
                    "supports_buy": "buy" in types,
                    "has_rent_template": "rent" in cls.URL_TEMPLATES,
                    "has_buy_template": "buy" in cls.URL_TEMPLATES,
                    "class_default": sorted(cls.SUPPORTED_TYPES),
                }
            )
    return render_template("scrapers.html", scrapers=scrapers_list)


@bp.route("/preview-url")
def preview_url():
    """Read-only: 302 to the exact URL a scraper would fetch, so the admin can
    inspect a site's inventory for a city before enabling. Byte-identical to
    BaseScraper.build_url — same single source of truth the runner uses."""
    scraper_key = (request.args.get("scraper_key") or "").strip()
    listing_type = (request.args.get("listing_type") or "").strip()
    city_slug = (request.args.get("city_slug") or "").strip()
    city_name = (request.args.get("city_name") or "").strip()
    custom_url = (request.args.get("custom_url") or "").strip() or None

    cls = SCRAPERS.get(scraper_key)
    if cls is None:
        return f"Onbekende scraper: {scraper_key}", 404

    url = cls.build_url(
        city_slug=city_slug,
        city_name=city_name,
        listing_type=listing_type,
        custom_url=custom_url,
    )
    if not url:
        return (
            f"Geen URL beschikbaar voor {scraper_key}/{listing_type} "
            f"in {city_name or city_slug}. Deze scraper heeft een eigen URL nodig.",
            200,
        )
    return redirect(url)


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
                "city": r.city,
                "listing_type": r.listing_type,
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
