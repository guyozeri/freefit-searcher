# FreeFit tools

Tools for [FreeFit](https://www.freefit.co.il/) (Israel): a web app that
searches every club and books classes, plus a Python CLI for the same.

## The web app (`docs/`)

`docs/index.html` is a static, map-based club search page **that can also book
classes**. It is published via GitHub Pages and needs no backend:

- **Browsing is public** — the club dataset is committed as
  `docs/_clubs_data.js` and refreshed daily (see below), so anyone can search
  and view clubs on the map without logging in.
- **Booking is per-user** — the FreeFit API sends `Access-Control-Allow-Origin: *`,
  so the browser calls it directly. A visitor clicks **Log in to book**, enters
  their own phone number, gets an SMS code, and from then on their device token
  lives only in their browser's `localStorage`. They can then view a club's
  lessons, book, see **My bookings**, and cancel — all client-side. No shared
  secret is ever in the page.

`docs/_freefit_api.js` is the browser client (auth, lessons, book, cancel).

### Run it locally

```
python -m http.server 8000 --directory docs
# open http://localhost:8000
```

### Daily club refresh

`.github/workflows/daily-clubs.yml` runs once a day: it calls `fetch_clubs.py`
with a maintainer token (stored as the Actions secrets `FREEFIT_PHONE`,
`FREEFIT_ID`, `FREEFIT_TOKEN`, `FREEFIT_BINID`), rebuilds the data, and commits
`docs/_clubs_data.js` / `docs/_city_coords.js` if anything changed. That is the
"fetch each day, load from cache" mechanism — visitors always get fresh data
without authenticating. Get the token values from your `freefit_config.json`
after `python book.py login`.

## Building the club dataset

The web app loads a committed dataset. Regenerate it manually with:

Two ways to build the dataset:

**From the mobile API (recommended).** One authenticated call returns all
clubs with coordinates *and* the IDs needed to book — no scraping, no geocoding:

```
pip install -r requirements.txt
python fetch_clubs.py       # GetMobileFullData -> output/clubs_*.json + address_coords.json
python build_js.py          # -> output/_clubs_data.js, _city_coords.js
cp output/_clubs_data.js output/_city_coords.js docs/   # serve the fresh data
```

(The daily GitHub Action does exactly these steps.)

**From the public WordPress site (original, no login).** Slower, and the IDs
are WordPress post IDs (not bookable):

```
python scrape.py            # clubs + activities -> output/*.json / *.csv
python geocode_cities.py    # add city coordinates
python geocode_addresses.py # add per-club coordinates
python build_js.py
python build_lookups.py     # taxonomy lookups
```

## The Telegram bot (`bot.py`)

A multi-user Telegram bot — each Telegram user logs into their **own** FreeFit
account and books for themselves. Their device token is stored in
`bot_sessions.json` (gitignored).

```
pip install -r requirements.txt
python fetch_clubs.py                     # once, so /clubs can search (writes output/clubs_api.json)
export TELEGRAM_BOT_TOKEN=123456:ABC...   # from @BotFather
python bot.py
```

Commands: `/login` (phone → SMS code), `/logout`, `/mybookings` (with cancel
buttons), `/clubs <query>` (tap a result to see its lessons), `/lessons <clubId>`
(with book buttons). Phone numbers and SMS codes pass through the Telegram
chat, so run the bot somewhere you trust.

## The CLI (`book.py`)

Same booking capability from the terminal — talks to the mobile app backend
(`ffservice.freefit.co.il/MobileManagementService`) to list classes and
book/cancel on your account.

```
python book.py login              # SMS-verify once; token is saved to freefit_config.json
python book.py orders             # your current bookings
python book.py clubs [query]      # search all clubs from the API
python book.py lessons <club>     # classes at a club
python book.py book <club> <RboxLessonID>
python book.py cancel <ClubOrderNum>
```

`<club>` is a raw `ClubID` (from `book.py clubs`, resolved against the list
`fetch_clubs.py` caches in `output/clubs_api.json`) or a friendly alias in
`freefit_config.json`. Copy `freefit_config.example.json` to
`freefit_config.json` and fill in your details (the real file is gitignored —
it holds your auth token).

### Auth model

A persistent per-device token authenticates every call. It is registered by
passing an SMS one-time code once (`book.py login`); after that no SMS is
needed. `book.py login --new` generates a brand-new token instead of reusing
the stored one (may log your phone's app out — use only if you want a
dedicated token for the script).

### How the two halves relate

When the dataset is built with `fetch_clubs.py`, each club's `id` **is** its
bookable `ClubID`, and `output/clubs_api.json` holds the `TerminalID` /
`BinType` needed to book. So search → book is a single ID: find a club with
`book.py clubs`, then `book.py book <ClubID> <lesson>`.

(The WordPress path uses a different ID space — post IDs, not bookable — which
is why the API path is preferred.)

## Reverse-engineering notes

`book.py` was built by capturing the iOS app's HTTPS traffic with mitmproxy
(no certificate pinning; plain JSON). `freefit_capture.py` is the mitmproxy
addon used to record and filter FreeFit calls. Endpoints are POST JSON with
the envelope `{"Error": 0, "Message": "...", "Data": "<json-string>"}` where
`Data` is itself a JSON string requiring a second parse.
