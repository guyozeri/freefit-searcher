#!/usr/bin/env python3
"""
Fetch the club list from the FreeFit mobile API — an alternative to scrape.py.

Where scrape.py reads the public WordPress site, this pulls the same club list
the app uses (GetMobileFullData -> ClubList), which is richer: it includes each
club's coordinates and, crucially, the IDs needed to book (RecordID / ClubID,
TerminalID, BinType). So the search site can be built straight from the API and
every club is bookable by book.py, with no geocoding step required.

Outputs (into output/, consumed by build_js.py):
    clubs_api.json       raw API records (includes TerminalID / BinType for booking)
    clubs_detailed.json  {id, title, address, description} in scrape.py's shape
    address_coords.json  {address: [lat, lng]} straight from the API

Usage:
    python fetch_clubs.py
    python build_js.py     # regenerate docs/_clubs_data.js from the API data
"""

import json
import os
import random
from pathlib import Path

import requests

BASE_URL = "https://ffservice.freefit.co.il/MobileManagementService"
CONFIG_PATH = Path(__file__).parent / "freefit_config.json"
OUTPUT_DIR = Path(__file__).parent / "output"

SESSION = requests.Session()
SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "FreeFit/2.2.20 (iPhone)",
})


def fetch_club_list(cfg: dict) -> list:
    """GetMobileFullData returns the full ClubList when called with BinID."""
    token = f"{random.randint(10, 20)}{cfg['token_base']}"
    resp = SESSION.post(f"{BASE_URL}/GetMobileFullData", timeout=60, data=json.dumps({
        "Phone": cfg["phone"],
        "BinID": cfg["bin_id"],
        "ID": cfg["id"],
        "Token": token,
    }))
    resp.raise_for_status()
    envelope = resp.json()
    if envelope.get("Error", 0) != 0:
        raise SystemExit(f"GetMobileFullData failed: {envelope.get('Message') or envelope}")
    data = json.loads(envelope["Data"])
    return data.get("ClubList", [])


# Unicode bidirectional control marks the API sprinkles into text fields.
_BIDI_MARKS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮"), None)


def _clean(text: str) -> str:
    return (text or "").translate(_BIDI_MARKS).strip()


def to_detailed(club: dict) -> dict:
    """Map an API club record to scrape.py's clubs_detailed.json shape."""
    address = _clean(club.get("Address"))
    area = _clean(club.get("AreaName"))
    # build_js.py derives the city from the text after the last comma; make sure
    # the clean AreaName is there even when the raw address omits it.
    if area and (area not in address):
        address = f"{address}, {area}" if address else area
    return {
        "id": club["RecordID"],
        "title": _clean(club.get("Name")),
        "address": address,
        "description": _clean(club.get("ClubTypeName")),
        # Booking constants (not user secrets — same for everyone, needed to book).
        "terminal_id": club.get("TerminalID"),
        "bin_type": club.get("BinType"),
        "is_rbox": club.get("IsStudioRbox", False),
    }


def load_config() -> dict:
    """Config from freefit_config.json, or from env vars (for CI)."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    env = {
        "phone": os.environ.get("FREEFIT_PHONE"),
        "id": os.environ.get("FREEFIT_ID"),
        "token_base": os.environ.get("FREEFIT_TOKEN"),
        "bin_id": os.environ.get("FREEFIT_BINID"),
    }
    if not all(env.values()):
        raise SystemExit("No freefit_config.json and FREEFIT_* env vars are incomplete.")
    return env


def main():
    cfg = load_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching club list from the FreeFit mobile API...")
    clubs = fetch_club_list(cfg)
    print(f"  Got {len(clubs)} clubs")

    # A soft failure (Error:0 but empty/degraded ClubList from a stale token or
    # partial outage) must not overwrite and auto-commit an empty dataset.
    if len(clubs) < 100:
        raise SystemExit(f"Refusing to overwrite data: only {len(clubs)} clubs returned "
                         "(expected ~2600). Leaving the last-good data in place.")

    (OUTPUT_DIR / "clubs_api.json").write_text(
        json.dumps(clubs, ensure_ascii=False, indent=2), encoding="utf-8")

    detailed = [to_detailed(c) for c in clubs]
    (OUTPUT_DIR / "clubs_detailed.json").write_text(
        json.dumps(detailed, ensure_ascii=False, indent=2), encoding="utf-8")

    coords = {}
    for c, d in zip(clubs, detailed):
        lat, lng = c.get("latitude"), c.get("longitude")
        if lat and lng:
            coords[d["address"]] = [round(float(lat), 6), round(float(lng), 6)]
    (OUTPUT_DIR / "address_coords.json").write_text(
        json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote clubs_api.json, clubs_detailed.json ({len(detailed)} clubs), "
          f"address_coords.json ({len(coords)} located)")
    print("Next: python build_js.py")


if __name__ == "__main__":
    main()
