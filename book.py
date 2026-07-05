#!/usr/bin/env python3
"""
FreeFit booking CLI — a single-user front-end over freefit_client.py.

Your credentials live in freefit_config.json (gitignored). Auth is registered
once via SMS (`login`); after that the stored token is reused.

Usage:
    python book.py login              # SMS-verify + save the existing/generated token
    python book.py login --new        # generate a FRESH device token, then SMS-verify it
    python book.py orders             # list your current bookings
    python book.py clubs [query]      # search the club list from the API
    python book.py lessons <club>     # list classes at a club
    python book.py book <club> <RboxLessonID>
    python book.py cancel <ClubOrderNum>

<club> is either a raw ClubID (resolved against the list fetch_clubs.py caches)
or a friendly alias defined in freefit_config.json.
"""

import argparse
import json
import sys
from pathlib import Path

import freefit_client as ff

CONFIG_PATH = Path(__file__).parent / "freefit_config.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def do_login(cfg: dict, generate_new: bool):
    token_base = ff.make_device_token() if generate_new else (cfg.get("token_base") or ff.make_device_token())
    if generate_new:
        print(f"Generated a new device token: {token_base}")
    ff.send_sms_code(cfg["phone"])
    code = input("Enter the SMS code: ").strip()
    session = ff.verify_and_login(cfg["phone"], code, token_base=token_base,
                                  push_token=cfg.get("push_token"),
                                  app_ver=cfg.get("app_ver", ff.DEFAULT_APP_VER))
    cfg.update({k: session[k] for k in
                ("token_base", "push_token", "id", "card_number", "bin_id") if session.get(k)})
    save_config(cfg)
    print(f"Logged in as {session.get('first_name') or cfg['phone']}; token saved.")


def resolve_club(cfg: dict, key: str) -> dict:
    alias = cfg.get("clubs", {}).get(key)
    if alias and alias.get("terminal_id"):
        return {"club_id": str(alias["club_id"]), "terminal_id": str(alias["terminal_id"]),
                "bin_type": alias.get("bin_type", 2)}
    club_id = str(alias["club_id"]) if alias else key
    club = ff.find_club(cfg, club_id)
    if not club or not club.get("terminal_id"):
        raise SystemExit(f"Club '{key}' not found or not bookable (no terminal). "
                         "Run `python fetch_clubs.py`, or pass a numeric ClubID.")
    return club


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
        for o in ff.get_orders(cfg):
            print(f"[{o['ID']}] {o.get('SupplyDate','?')}  {o.get('LessonName','?')}  @ {o.get('ClubName','?')}")

    elif args.cmd == "clubs":
        matches = ff.search_clubs(cfg, args.query, limit=0)
        for c in matches:
            print(f"{c['RecordID']:>7}  {(c.get('Name') or '').strip()}  —  {(c.get('AreaName') or '').strip()}")
        print(f"\n{len(matches)} club(s)" + (f" matching '{args.query}'" if args.query.strip() else ""))

    elif args.cmd == "lessons":
        club = resolve_club(cfg, args.club)
        for l in ff.get_lessons(cfg, club["club_id"]):
            flags = []
            if l.get("IsUserBooked"):
                flags.append("BOOKED")
            if l.get("IsLessonFull"):
                flags.append("FULL")
            print(f"{l['LessonStartDate']}  id={l['RboxLessonID']}  {l['LessonName']}  "
                  f"({l.get('SlotsAvailable','?')} slots) {' '.join(flags)}")

    elif args.cmd == "book":
        club = resolve_club(cfg, args.club)
        lessons = ff.get_lessons(cfg, club["club_id"])
        match = next((l for l in lessons if str(l["RboxLessonID"]) == args.rbox_lesson_id), None)
        if not match:
            raise SystemExit(f"Lesson {args.rbox_lesson_id} not found in {args.club}'s current schedule.")
        print("Booking:", match["LessonStartDate"], match["LessonName"])
        print("->", ff.book(cfg, club, match))

    elif args.cmd == "cancel":
        print("->", ff.cancel(cfg, args.club_order_num))


if __name__ == "__main__":
    try:
        main()
    except ff.FreeFitError as e:
        print(f"FreeFit error: {e}", file=sys.stderr)
        sys.exit(1)
