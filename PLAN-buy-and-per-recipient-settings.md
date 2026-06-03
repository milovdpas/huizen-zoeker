# Add Buy (koop) support + per-recipient, multi-city preferences

## Context

`huizen-zoeker` is a Flask + SQLAlchemy + MySQL app that scrapes Dutch housing sites and emails recipients about new listings. Today it is **rental-only** and **single-config**:

- Every scraper is a hardcoded class with a fixed `START_URL` baked to one city and `/huur/` (rent). Cities are limited to **Oss** and **Berghem** via per-city subclasses (`FundaOss`, `FundaBerghem`, `DirectwonenOss`, …) plus single-city scrapers. `scrapers/__init__.py` holds a static `ALL_SCRAPERS` list.
- There is **one global** `Settings.max_price_cents`, and **every** `EmailRecipient` receives **every** new listing in Oss/Berghem under that price. `House.notified` (a bool) prevents re-sends.

We want two things:

1. **Buy (koop)** support alongside rent (huur). A listing now has a type.
2. A **per-recipient** Settings experience: each email chooses which **cities** they want, whether they want **rent** and/or **buy**, and a **separate max price** for each. Cities must be **scalable** — a DB-backed catalog editable in the UI, where the admin can enable specific scrapers per city, **preview** the generated scraper URL, and set a **custom URL override** when a site's URL can't be templated.

Outcome: an admin adds cities and enables scrapers for them; recipients self-select cities + rent/buy + price caps; the system scrapes only what someone wants, stores rent and buy listings, and emails each recipient only their matching new listings.

---

## Per-site parametrization facts (verified by reading each scraper)

| Scraper | City in URL | Buy (koop) | Notes |
|---|---|---|---|
| **funda** | `selected_area=["{slug}"]` | yes (`/zoeken/koop/`) | price detection needs work for buy (see below) |
| **deleygraaf** | path `/{SLUG_UPPER}/+10km/` | yes (`/koop/`) | `parse()` hardcodes `/huur/` filter — must branch on type |
| **krabben** | `search={City}` | yes (`price_type=sale`) | makelaar, sells too |
| **directwonen** | path `/{slug}` | likely (`koopwoningen-kopen/{slug}`) | verify via preview during impl |
| **easyleasewonen** | `location={City}` | no | rent-only site |
| **gapph** | `region_search={slug}` | no | short-stay rental only |
| **rncwonen** | Drupal **taxonomy ID** (`...=718`) | no | **cannot** template by city name → custom-URL only |

> **Removed**: `funda-digimakelaars` (a per-makelaar source that doesn't generalize across cities) is dropped entirely — plain Funda covers it. Delete the `FundaDigimakelaars` class and its registry entry; do not seed any `CityScraper` rows for it.

So the per-city/type **URL** is only half the job: the **parsers** are also rent-coupled and must become type-aware where rent/buy differ (see Scrapers section).

---

## Data model changes — new Alembic migration `0002`

Model file: `huizenzoeker/models.py`. Migration template: `alembic/versions/0001_initial.py`.

**New tables / columns:**

- `City(id, name, slug UNIQUE, enabled BOOL default 1, created_at)` — the scalable catalog. `slug` is the canonical lowercase form; admin-editable (sites disagree on slugs, e.g. `den-bosch` vs `s-hertogenbosch`).
- `EmailRecipient` gains: `wants_rent BOOL`, `max_rent_cents INT NULL`, `wants_buy BOOL`, `max_buy_cents INT NULL`. (`NULL`/`0` = no cap, keeping the existing `0 = no max` convention, now per type.)
- `recipient_cities(recipient_id, city_id)` join, PK both, FK cascade — recipient ↔ cities many-to-many.
- `CityScraper(id, city_id FK, scraper_key STR(64), listing_type STR(8), enabled BOOL, custom_url STR(1000) NULL)` with `UNIQUE(city_id, scraper_key, listing_type)` — per-(city, scraper, type) enablement + optional URL override. Only types in a scraper's `SUPPORTED_TYPES` get rows.
- `House` gains `listing_type STR(8) NOT NULL`. Drop `UNIQUE(address_normalized)`, add composite `UNIQUE(address_normalized, listing_type)` (the same property can be both a rent and a buy listing). Drop the `notified` column (replaced below).
- `notifications(house_id, recipient_id, sent_at)` PK `(house_id, recipient_id)` — per-recipient send log; existence = "already sent". Idempotent insert-or-ignore. Replaces `House.notified`.
- `ScrapeRun` gains `city STR(100) NULL`, `listing_type STR(8) NULL` — one run row per (scraper_key, city, type) job, so a Funda-Oss-rent failure doesn't mark Funda-Berghem-buy failed.

**Migration data steps (preserve current behavior):**

1. Backfill `House.listing_type = 'rent'` (all existing rows are rentals), then swap the unique constraint (MySQL: drop old unique index before adding the composite). Keep `ix_houses_address_normalized`.
2. Seed `City`: Oss, Berghem (slugs `oss`, `berghem`).
3. For every existing `EmailRecipient`: set `wants_rent=1, max_rent_cents = Settings.max_price_cents, wants_buy=0`; add `recipient_cities` rows for Oss + Berghem.
4. Seed `CityScraper` **rent** rows for the (city, scraper) combos that exist today (Oss+Berghem × the current scrapers, per each scraper's `SUPPORTED_TYPES`). RNC gets a `custom_url` copied from its current hardcoded `START_URL`. (Funda-Digimakelaars is removed — no rows.)
5. Copy existing `notified=True` houses into `notifications` for every existing recipient (so nobody gets re-emailed about already-sent houses), then drop `House.notified`.
6. `Settings.max_price_cents` stays only as the migration source; the runner stops reading it.

---

## Scrapers — parametrize construction + URL, keep bespoke parsers

Approach (lowest-risk): **parametrize the instances, keep each site's `parse()`**; thread `listing_type` only where rent/buy actually differ.

**`BaseScraper`** (`huizenzoeker/scrapers/base.py`) gains:

```python
SCRAPER_KEY: str            # stable id, e.g. "funda"
DISPLAY_NAME: str
SUPPORTED_TYPES: set[str]   # {"rent"} or {"rent", "buy"}
URL_TEMPLATES: dict[str, str] = {}   # {"rent": "...{slug}...", "buy": "..."}; empty => custom-URL only

@classmethod
def build_url(cls, *, city_slug, city_name, listing_type, custom_url=None) -> str | None:
    # custom_url wins; else render the template (supports {slug}, {slug_upper}, {city}); else None
def __init__(self, *, city_name, city_slug, listing_type, url_override=None):
    # sets self.START_URL = build_url(...); stores self.listing_type, self.city_hint = city_name
```

`build_url` is the **single source of truth** used by both the runner and the Settings preview links — the preview is byte-identical to what gets fetched.

**Per-site edits:**

- Delete per-city subclasses (`FundaOss`, `FundaBerghem`, `DirectwonenOss`, `DirectwonenBerghem`) and the `FundaDigimakelaars` class entirely; drop `CITY_HINT` constants; replace with `SCRAPER_KEY`, `SUPPORTED_TYPES`, `URL_TEMPLATES`, instance attributes.
- **funda.py**: templates for rent (`/zoeken/huur/`) + buy (`/zoeken/koop/`). Fix `_find_price_for` — it currently only matches cards containing `"maand"` (rent). For buy, match `k.k.`/`v.o.n.` price blocks. `SUPPORTED_TYPES={"rent","buy"}`.
- **deleygraaf.py**: `parse()` hardcodes `if "/huur/" not in href: continue` — branch on `self.listing_type` to accept `/koop/`. Template uses `{slug_upper}`. `{"rent","buy"}`.
- **krabben.py**: template swaps `price_type=rental`↔`sale`, `search={city_name}`. `{"rent","buy"}`.
- **directwonen.py**: templates `huurwoningen-huren/{slug}` + `koopwoningen-kopen/{slug}` (verify buy path via preview during impl).
- **easyleasewonen.py** (`location={city}`), **gapph.py** (`region_search={slug}`): city template, `SUPPORTED_TYPES={"rent"}`.
- **rncwonen.py**: `URL_TEMPLATES={}` (custom-URL only), `{"rent"}`.

**Registry** (`huizenzoeker/scrapers/__init__.py`): replace `ALL_SCRAPERS: list[type]` with `SCRAPERS: dict[str, type[BaseScraper]]` keyed by `SCRAPER_KEY`.

**normalize.py** (`huizenzoeker/normalize.py`): add a `slugify(name)` helper (reuse the existing NFKD/strip-diacritics logic from `normalize_address`). Add `k.k.`, `v.o.n.`, `kosten koper` to the strip regex in `parse_price_to_cents` so buy prices aren't mangled.

---

## Runner — coverage, jobs, per-recipient notify

`huizenzoeker/scrapers/runner.py`:

- **Coverage = union of recipient prefs ∩ enabled `CityScraper`** (chosen model). At cycle start, snapshot a job list: the set of `(city, listing_type)` at least one recipient wants (`recipient_cities` × `wants_rent`/`wants_buy`), intersected with enabled `CityScraper` rows. Snapshot once so a mid-cycle toggle doesn't corrupt the in-flight run.
- For each job, instantiate `SCRAPERS[scraper_key](city_name=…, city_slug=…, listing_type=…, url_override=custom_url)`, run, and create one `ScrapeRun(source=scraper_key, city=…, listing_type=…)`.
- `_upsert_house` tags `House.listing_type`; scope the address-fallback dedup query by `listing_type` too (source_url lookup stays type-agnostic — one URL is one listing).
- Replace `TARGET_CITIES`/`_is_in_target_area` (hardcoded Oss/Berghem) with the city of the job (listings are already scoped by the per-city URL; keep a light sanity check against the job's city).
- **Per-recipient notify**: for each NEW house this run, select recipients where the house's city ∈ their `recipient_cities`, they `want` the house's `listing_type`, and `price_cents <= their per-type cap` (NULL/0 = no cap). Send via `send_listing_notification`, then insert `notifications(house_id, recipient_id)` (insert-or-ignore). Drives off per-run newness, not "no notification row" — so a newly-added recipient gets only future listings, never a backfill dump.
- **Warm-up safeguard**: the first time a `(city, listing_type)` combo is scraped it has no history, so every current listing is "new" and would flood matching recipients. If a job's `(city, listing_type)` had **zero** existing houses before this run, insert the houses but **skip notifications** for that combo this cycle (log how many were suppressed). Subsequent runs notify normally. This keeps "you only get genuinely new listings".

---

## Routes + templates

`huizenzoeker/routes.py`, templates in `huizenzoeker/templates/`:

**Settings page — per recipient** (`settings.html`): when adding/editing a recipient, show city checkboxes (from `City` catalog), a rent toggle + max-rent field, a buy toggle + max-buy field. Reuse `_eur_to_cents` (`routes.py`) for both price fields. POST actions: add/edit/delete recipient + their cities/prefs.

**City admin** (new section or page, linked from `base.html` nav): list/add/remove cities (name + slug, `enabled`). Per city, show each scraper × supported type with: an **enable** checkbox, a **custom URL** field, and a **Preview** link (`target="_blank"`) whose href comes from a thin read-only route calling `BaseScraper.build_url(...)`. This is where the admin "investigates" whether a site has inventory for a city before enabling buy/rent.

**Houses list** (`houses.html`): add a `listing_type` column/pill (Huur/Koop) and optionally a filter. `notified` pill logic now derives from presence of any `notifications` row (or simply drop the per-house global status and show count).

**Email** (`notifier.py`, `email_notification.html`): subject/body currently hardcode "huurwoning" and "per maand". Branch wording on `house.listing_type` (rent → "huurwoning … per maand"; buy → "koopwoning … koopprijs").

**Scheduler** (`scheduler.py`): `trigger_source` / `run_source` now target a `scraper_key` and expand to all its enabled `(city, type)` jobs (re-snapshot at trigger time). Cookie-refresh scheduling is unaffected; note Funda now runs more jobs per cycle on one Cloudflare session — consider serializing Funda jobs / a small delay (not a blocker).

---

## Key decisions (with rationale)

- **Coverage = union ∩ enablement** — avoids scraping combos nobody wants. The first-scrape flood risk this creates is handled by the **warm-up safeguard** above.
- **`notifications` table over `House.notified`** — a bool can't express "sent to A, not B" once prefs differ per recipient. Only-future semantics; existing sends migrated so nobody is re-emailed.
- **Keep bespoke parsers** — each site already has custom parsing; only thread `listing_type` where rent/buy differ. Lower risk than unifying parsers.
- **Explicit `City.slug`** (not auto-derived at scrape time) — sites disagree on slugs/casing; templates carry the case transform (`{slug}` vs `{slug_upper}`).
- **Custom-URL-only scraper** (RNC) — its taxonomy-ID URL can't be templated; the override field is the escape hatch. (Digimakelaars removed.)

---

## Verification

1. **Migration**: run `alembic upgrade head` against a dev DB (or a fresh DB seeded with a few rental houses + a recipient). Confirm: existing recipient now has `wants_rent=1`, max = old global, Oss+Berghem; existing houses are `listing_type='rent'`; no re-notification rows missing; `CityScraper` rent rows seeded.
2. **URL templating / preview**: in the City admin, add a city (e.g. Nijmegen), open the **Preview** links for funda rent + buy and deleygraaf — confirm the opened URLs are valid search pages with listings. Verify RNC shows a custom-URL field (no template).
3. **Scrape run**: enable funda rent+buy for one city, set a recipient wanting both with sane caps, hit **Run now** (or `run-source funda`). Confirm: `ScrapeRun` rows per (city, type); houses stored with correct `listing_type`; the **first** run suppresses emails (warm-up) and logs the count; a **second** run emails only genuinely new listings, and only to matching recipients within their per-type cap.
4. **Per-recipient filtering**: two recipients — one rent-only Oss, one buy-only Nijmegen — confirm each gets only their matching type/city, and `notifications` rows prevent re-sends on the next run.
5. **Buy price parsing**: confirm a `€ 325.000,- k.k.` listing parses to the right cents (not mangled by the `k.k.` token) and respects the buy cap.
6. Run any existing tests; do a quick `python -c "import huizenzoeker..."`/app boot to catch import/registry errors after the `ALL_SCRAPERS` → `SCRAPERS` change.
