# FreeFit tools

Two complementary tools for [FreeFit](https://www.freefit.co.il/) (Israel).

## 1. Searcher (discovery)

A static, map-based club search page (`docs/index.html`, published via GitHub
Pages) built from a club dataset.

Two ways to build the dataset:

**From the mobile API (recommended).** One authenticated call returns all
clubs with coordinates *and* the IDs needed to book — no scraping, no geocoding:

```
pip install -r requirements.txt
python fetch_clubs.py       # GetMobileFullData -> output/clubs_*.json + address_coords.json
python build_js.py          # -> output/_clubs_data.js, _city_coords.js
```

**From the public WordPress site (original, no login).** Slower, and the IDs
are WordPress post IDs (not bookable):

```
python scrape.py            # clubs + activities -> output/*.json / *.csv
python geocode_cities.py    # add city coordinates
python geocode_addresses.py # add per-club coordinates
python build_js.py
python build_lookups.py     # taxonomy lookups
```

## 2. Booking (`book.py`) — the authenticated half

Talks to the **mobile app backend** (`ffservice.freefit.co.il/MobileManagementService`)
to list classes and book/cancel them on your account.

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
