#!/usr/bin/env python3
"""
FreeFit booking client — the authenticated counterpart to scrape.py.

Where scrape.py reads the public WordPress site (website.freefit.co.il) to
discover clubs, this talks to the mobile app's backend
(ffservice.freefit.co.il/MobileManagementService) to list classes and
book/cancel them on your account.

Auth: a persistent per-device token, registered by passing an SMS check once
(see `login`). After that no SMS is needed — the token is stored in
freefit_config.json and reused. All endpoints are POST JSON and return
{"Error": 0, "Message": "...", "Data": "<json-string>"} (Data is a nested
JSON string that needs a second parse).

Usage:
    python book.py login              # SMS-verify + save the existing/generated token
    python book.py login --new        # generate a FRESH device token, then SMS-verify it
    python book.py orders             # list your current bookings
    python book.py clubs [query]      # search the club list from the API
    python book.py lessons <club>     # list classes at a club
    python book.py book <club> <RboxLessonID>
    python book.py cancel <ClubOrderNum>

<club> is either a raw ClubID (from `clubs`, resolved against the list that
fetch_clubs.py caches) or a friendly alias defined in freefit_config.json.
"""

import argparse
import json
import random
import secrets
from pathlib import Path

import requests

BASE_URL = "https://ffservice.freefit.co.il/MobileManagementService"
CONFIG_PATH = Path(__file__).parent / "freefit_config.json"
CLUBS_CACHE = Path(__file__).parent / "output" / "clubs_api.json"

SESSION = requests.Session()
SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "FreeFit/2.2.20 (iPhone)",
})


# ---- Config ---------------------------------------------------------------

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_device_token() -> str:
    """A fresh 32-hex-char device token, same shape the app generates at install."""
    return secrets.token_hex(16)


def make_token(token_base: str) -> str:
    """The app prepends 2 random digits to the base token; the server ignores them."""
    return f"{random.randint(10, 20)}{token_base}"


# ---- Transport ------------------------------------------------------------

def call(method: str, payload: dict):
    """POST to an endpoint, unwrap the envelope, and parse the inner Data JSON."""
    resp = SESSION.post(f"{BASE_URL}/{method}", data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    envelope = resp.json()

    if envelope.get("Error", 0) != 0:
        raise SystemExit(f"{method} failed: {envelope.get('Message') or envelope}")

    data = envelope.get("Data")
    if isinstance(data, str) and data:
        try:
            return json.loads(data), envelope.get("Message", "")
        except json.JSONDecodeError:
            return data, envelope.get("Message", "")
    return data, envelope.get("Message", "")


# ---- Auth -----------------------------------------------------------------

def send_sms_code(cfg: dict):
    call("SendSmsCode", {"Phone": cfg["phone"]})
    print(f"SMS code sent to {cfg['phone']}.")


def verify_sms_code(cfg: dict, code: str, token_base: str):
    """Register `token_base` against the account by passing the SMS check, then persist it."""
    data, _ = call("VerifySmsCode", {
        "DeviceType": "iphone",
        "DeviceConfStr": '[{"os_version":"26.5.1"},{"device_config":"UNDEFINED"},{"language":"English"}]',
        "PushToken": cfg["push_token"],
        "Code": code,
        "IgnoreOtpCode": False,
        "Phone": cfg["phone"],
        "AppVer": cfg["app_ver"],
        "Token": make_token(token_base),
    })
    cfg["token_base"] = token_base
    if isinstance(data, dict) and data.get("RecordID"):
        cfg["id"] = str(data["RecordID"])
    save_config(cfg)
    print("Verified and saved token to config. Account:", data)


def do_login(cfg: dict, generate_new: bool):
    """Full auth flow: pick a token, request an SMS code, verify, persist."""
    token_base = make_device_token() if generate_new else (cfg.get("token_base") or make_device_token())
    if generate_new:
        print(f"Generated a new device token: {token_base}")
    send_sms_code(cfg)
    code = input("Enter the SMS code: ").strip()
    verify_sms_code(cfg, code, token_base)


# ---- Data / booking -------------------------------------------------------

def get_orders(cfg: dict) -> list:
    data, _ = call("GetClubOrders", {
        "Phone": cfg["phone"],
        "Token": make_token(cfg["token_base"]),
        "ID": cfg["id"],
    })
    return data or []


def get_club_list(cfg: dict) -> list:
    """The app's full club list (GetMobileFullData -> ClubList), cached to output/."""
    if CLUBS_CACHE.exists():
        return json.loads(CLUBS_CACHE.read_text(encoding="utf-8"))
    data, _ = call("GetMobileFullData", {
        "Phone": cfg["phone"],
        "BinID": cfg["bin_id"],
        "ID": cfg["id"],
        "Token": make_token(cfg["token_base"]),
    })
    clubs = data.get("ClubList", []) if isinstance(data, dict) else []
    if clubs:
        CLUBS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CLUBS_CACHE.write_text(json.dumps(clubs, ensure_ascii=False, indent=2), encoding="utf-8")
    return clubs


def get_lessons(cfg: dict, club_id) -> list:
    data, _ = call("GetClubLessonList", {
        "Token": make_token(cfg["token_base"]),
        "ID": cfg["id"],
        "ClubID": str(club_id),
        "Phone": cfg["phone"],
    })
    return data or []


def book(cfg: dict, club: dict, lesson: dict) -> str:
    """lesson is one item from get_lessons(); club is a config club dict."""
    _, message = call("ClubOrder", {
        "Phone": cfg["phone"],
        "BinType": club["bin_type"],
        "LessonName": lesson["LessonName"],
        "IsCancelAllow": lesson.get("IsCancelAllow", False),
        "Token": make_token(cfg["token_base"]),
        "PreOrderDate": lesson["LessonStartDate"],
        "RboxLessonID": str(lesson["RboxLessonID"]),
        "ID": cfg["id"],
        "ClubID": str(club["club_id"]),
        "IsOnlyCheckWithoutTransaction": "false",
        "LessonStartDate": lesson["LessonStartDate"],
        "CancelationTime": str(lesson.get("CancelationTime", 0.0)),
        "LessonEndDate": lesson["LessonEndDate"],
        "IsRbox": True,
        "CardNumber": cfg["card_number"],
        "IsSubscriptionOrder": "true",
        "TerminalID": str(club["terminal_id"]),
        "CoachName": lesson.get("CoachName", ""),
    })
    return message


def cancel(cfg: dict, order_num) -> str:
    _, message = call("CancelClubOrder", {
        "Token": make_token(cfg["token_base"]),
        "Phone": cfg["phone"],
        "ClubOrderNum": str(order_num),
        "ID": cfg["id"],
    })
    return message


# ---- CLI ------------------------------------------------------------------

def resolve_club(cfg: dict, key: str) -> dict:
    """Resolve a club by config alias or by raw ClubID (from the fetched club list)."""
    alias = cfg.get("clubs", {}).get(key)
    if alias and alias.get("terminal_id"):
        return {"club_id": str(alias["club_id"]), "terminal_id": str(alias["terminal_id"]),
                "bin_type": alias.get("bin_type", cfg.get("bin_type", 2))}

    club_id = str(alias["club_id"]) if alias else key
    for c in get_club_list(cfg):
        if str(c["RecordID"]) == club_id:
            return {"club_id": club_id, "terminal_id": str(c["TerminalID"]), "bin_type": c["BinType"]}

    raise SystemExit(f"Club '{key}' not found. Run `python fetch_clubs.py`, or pass a numeric ClubID.")


def main():
    parser = argparse.ArgumentParser(description="Book FreeFit classes from the command line")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="SMS-verify and save the device token")
    p_login.add_argument("--new", action="store_true", help="generate a fresh device token first")
    sub.add_parser("orders", help="list your current bookings")
    p_clubs = sub.add_parser("clubs", help="search the club list from the API")
    p_clubs.add_argument("query", nargs="?", default="", help="filter by name or address")
    p_lessons = sub.add_parser("lessons", help="list classes at a club (alias or ClubID)")
    p_lessons.add_argument("club")
    p_book = sub.add_parser("book", help="book a class")
    p_book.add_argument("club")
    p_book.add_argument("rbox_lesson_id")
    p_cancel = sub.add_parser("cancel", help="cancel a booking")
    p_cancel.add_argument("club_order_num")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "login":
        do_login(cfg, generate_new=args.new)

    elif args.cmd == "orders":
        for o in get_orders(cfg):
            print(f"[{o['ID']}] {o.get('SupplyDate','?')}  {o.get('LessonName','?')}  @ {o.get('ClubName','?')}")

    elif args.cmd == "clubs":
        q = args.query.strip()
        matches = [c for c in get_club_list(cfg)
                   if q in (c.get("Name") or "") or q in (c.get("Address") or "")]
        for c in matches:
            print(f"{c['RecordID']:>7}  {(c.get('Name') or '').strip()}  —  {(c.get('AreaName') or '').strip()}")
        print(f"\n{len(matches)} club(s)" + (f" matching '{q}'" if q else ""))

    elif args.cmd == "lessons":
        club = resolve_club(cfg, args.club)
        for l in get_lessons(cfg, club["club_id"]):
            flags = []
            if l.get("IsUserBooked"):
                flags.append("BOOKED")
            if l.get("IsLessonFull"):
                flags.append("FULL")
            print(f"{l['LessonStartDate']}  id={l['RboxLessonID']}  {l['LessonName']}  "
                  f"({l.get('SlotsAvailable','?')} slots) {' '.join(flags)}")

    elif args.cmd == "book":
        club = resolve_club(cfg, args.club)
        lessons = get_lessons(cfg, club["club_id"])
        match = next((l for l in lessons if str(l["RboxLessonID"]) == args.rbox_lesson_id), None)
        if not match:
            raise SystemExit(f"Lesson {args.rbox_lesson_id} not found in {args.club}'s current schedule.")
        print("Booking:", match["LessonStartDate"], match["LessonName"])
        print("->", book(cfg, club, match))

    elif args.cmd == "cancel":
        print("->", cancel(cfg, args.club_order_num))


if __name__ == "__main__":
    main()
