# FreeFit tools

Two complementary tools for [FreeFit](https://www.freefit.co.il/) (Israel).

## 1. Searcher (discovery) — the original project

Scrapes the public WordPress site (`website.freefit.co.il`) into a searchable
club/activity database and a static map-based search page.

```
pip install -r requirements.txt
python scrape.py            # clubs + activities -> output/*.json / *.csv
python geocode_cities.py    # add city coordinates
python geocode_addresses.py # add per-club coordinates
python build_js.py          # -> docs/_clubs_data.js, docs/_city_coords.js
python build_lookups.py     # taxonomy lookups
# docs/index.html is the published search UI (GitHub Pages)
```

Data source: the WordPress REST API + Elementor page markup. No login.

## 2. Booking (`book.py`) — the authenticated half

Talks to the **mobile app backend** (`ffservice.freefit.co.il/MobileManagementService`)
to list classes and book/cancel them on your account.

```
python book.py login              # SMS-verify once; token is saved to freefit_config.json
python book.py orders             # your current bookings
python book.py lessons <club>     # classes at a configured club
python book.py book <club> <RboxLessonID>
python book.py cancel <ClubOrderNum>
```

`<club>` is a key in `freefit_config.json`'s `clubs` map. Copy
`freefit_config.example.json` to `freefit_config.json` and fill in your
details (the real file is gitignored — it holds your auth token).

### Auth model

A persistent per-device token authenticates every call. It is registered by
passing an SMS one-time code once (`book.py login`); after that no SMS is
needed. `book.py login --new` generates a brand-new token instead of reusing
the stored one (may log your phone's app out — use only if you want a
dedicated token for the script).

### How the two halves relate

The searcher's club `id` is a **WordPress post ID** and does **not** equal the
booking API's `ClubID` — they're separate ID spaces, and the public site does
not expose the bookable ID. So to book at a club you map it once in
`freefit_config.json` with its mobile `club_id`, `terminal_id`, and `bin_type`
(captured from a real booking). Fully automatic "search → book" across all
clubs would require the mobile app's own club-list endpoint, which is not yet
mapped.

## Reverse-engineering notes

`book.py` was built by capturing the iOS app's HTTPS traffic with mitmproxy
(no certificate pinning; plain JSON). `freefit_capture.py` is the mitmproxy
addon used to record and filter FreeFit calls. Endpoints are POST JSON with
the envelope `{"Error": 0, "Message": "...", "Data": "<json-string>"}` where
`Data` is itself a JSON string requiring a second parse.
