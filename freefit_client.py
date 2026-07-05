#!/usr/bin/env python3
"""
Shared FreeFit mobile-API client (ffservice.freefit.co.il/MobileManagementService).

Used by book.py (single-user CLI) and bot.py (multi-user Telegram bot). Every
authenticated call is driven by a `session` dict:

    {token_base, id, phone, card_number, bin_id, push_token, app_ver}

Auth is per-device: a 32-hex token is generated locally and registered by
passing an SMS check once (send_sms_code -> verify_and_login); after that the
stored token is reused. Endpoints are POST JSON returning
{"Error": 0, "Message": "...", "Data": "<json-string>"} where Data is a nested
JSON string (object or array) that needs a second parse.
"""

import json
import random
import secrets
from pathlib import Path

import requests

BASE_URL = "https://ffservice.freefit.co.il/MobileManagementService"
CLUBS_CACHE = Path(__file__).parent / "output" / "clubs_api.json"
DEFAULT_APP_VER = "2.2.20"

_HEADERS = {
    "Content-Type": "application/json",
    # The API 403s the default python-requests UA; any real UA is fine.
    "User-Agent": "FreeFit/2.2.20 (iPhone)",
}
_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


def new_http() -> requests.Session:
    """A fresh HTTP session (own cookie jar) — one per FreeFit user, so their
    server-side sessions don't collide when several people use the bot."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


class FreeFitError(Exception):
    """A FreeFit API call returned Error != 0 (message is user-facing Hebrew/English)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ---- token helpers --------------------------------------------------------

def make_device_token() -> str:
    """A fresh 32-hex-char device token, same shape the app generates at install."""
    return secrets.token_hex(16)


def make_token(token_base: str) -> str:
    """The app prepends 2 random digits to the base token; the server ignores them."""
    return f"{random.randint(10, 20)}{token_base}"


def fmt_float(v) -> str:
    """Match the app contract: floats keep a trailing .0 ('12' -> '12.0')."""
    if v is None:
        return "0.0"
    f = float(v)
    return f"{f:.1f}" if f == int(f) else str(f)


# ---- transport ------------------------------------------------------------

def call(method: str, payload: dict, http: requests.Session = None):
    """POST to an endpoint, unwrap the envelope, parse the inner Data JSON."""
    resp = (http or _SESSION).post(f"{BASE_URL}/{method}", data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    envelope = resp.json()

    code = envelope.get("Error", 0)
    if code != 0:
        raise FreeFitError(envelope.get("Message") or f"{method} failed (Error {code})", code=code)

    data = envelope.get("Data")
    if isinstance(data, str) and data:
        try:
            return json.loads(data), envelope.get("Message", "")
        except json.JSONDecodeError:
            return data, envelope.get("Message", "")
    return data, envelope.get("Message", "")


# ---- auth -----------------------------------------------------------------

# Server-side session expired; a fresh Login re-establishes it, then retry.
SESSION_EXPIRED_CODES = {11}


def send_sms_code(phone: str, http: requests.Session = None):
    call("SendSmsCode", {"Phone": phone}, http=http)


def _login_row(session: dict, http: requests.Session = None) -> dict:
    profile, _ = call("Login", {
        "Token": make_token(session["token_base"]), "ID": session["id"],
        "PushToken": session.get("push_token", ""), "Phone": session["phone"],
        "AppVer": session.get("app_ver", DEFAULT_APP_VER),
    }, http=http)
    row = profile[0] if isinstance(profile, list) and profile else profile
    return row if isinstance(row, dict) else {}


def login(session: dict, http: requests.Session = None) -> dict:
    """Re-establish the server-side session for a stored token. Returns fresh
    profile fields (card_number, bin_id) so callers can keep them current."""
    row = _login_row(session, http)
    return {
        "card_number": row.get("CardNumber", session.get("card_number", "")),
        "bin_id": row.get("BinID", session.get("bin_id", "")),
        "first_name": row.get("FirstName", session.get("first_name", "")),
    }


def _authed(session: dict, http, method: str, payload: dict):
    """Run a call; if the server session has expired, Login once and retry."""
    try:
        return call(method, payload, http=http)
    except FreeFitError as e:
        if e.code in SESSION_EXPIRED_CODES:
            _login_row(session, http)
            return call(method, payload, http=http)
        raise


def verify_and_login(phone: str, code: str, *, token_base: str = None,
                     push_token: str = None, app_ver: str = DEFAULT_APP_VER,
                     http: requests.Session = None) -> dict:
    """Register a device token via the SMS check, then Login for the profile.

    Returns a full session dict ready to persist. Raises FreeFitError on a bad code.
    """
    token_base = token_base or make_device_token()
    push_token = push_token or secrets.token_hex(16)

    verify, _ = call("VerifySmsCode", {
        "DeviceType": "web",
        "DeviceConfStr": '[{"os_version":"web"},{"device_config":"browser"},{"language":"he"}]',
        "PushToken": push_token,
        "Code": code,
        "IgnoreOtpCode": False,
        "Phone": phone,
        "AppVer": app_ver,
        "Token": make_token(token_base),
    }, http=http)
    record = verify[0] if isinstance(verify, list) and verify else verify
    account_id = str(record.get("RecordID", "")) if isinstance(record, dict) else ""
    if not account_id:
        raise FreeFitError("Verification did not return an account id.")

    session = {"token_base": token_base, "push_token": push_token,
               "app_ver": app_ver, "id": account_id, "phone": phone}
    session.update(login(session, http))
    return session


# ---- data / booking -------------------------------------------------------

def load_cached_clubs() -> list:
    """The daily-cached club directory (output/clubs_api.json), or [] if absent."""
    if CLUBS_CACHE.exists():
        return json.loads(CLUBS_CACHE.read_text(encoding="utf-8"))
    return []


def get_club_list(session: dict, http: requests.Session = None) -> list:
    """Full club list (GetMobileFullData -> ClubList); uses/refreshes the cache."""
    cached = load_cached_clubs()
    if cached:
        return cached
    data, _ = _authed(session, http, "GetMobileFullData", {
        "Phone": session["phone"], "BinID": session.get("bin_id", ""),
        "ID": session["id"], "Token": make_token(session["token_base"]),
    })
    clubs = data.get("ClubList", []) if isinstance(data, dict) else []
    if clubs:
        CLUBS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CLUBS_CACHE.write_text(json.dumps(clubs, ensure_ascii=False, indent=2), encoding="utf-8")
    return clubs


def find_club(session: dict, club_id, http: requests.Session = None) -> dict:
    """Booking constants for a club id: {club_id, terminal_id, bin_type} or None."""
    cid = str(club_id)
    for c in get_club_list(session, http):
        if str(c["RecordID"]) == cid:
            return {"club_id": cid, "terminal_id": c.get("TerminalID"), "bin_type": c.get("BinType", 2)}
    return None


def search_clubs(session: dict, query: str, limit: int = 20, http: requests.Session = None) -> list:
    q = (query or "").strip()
    matches = [c for c in get_club_list(session, http)
               if q in (c.get("Name") or "") or q in (c.get("Address") or "")]
    return matches[:limit] if limit else matches


def get_orders(session: dict, http: requests.Session = None) -> list:
    data, _ = _authed(session, http, "GetClubOrders", {
        "Phone": session["phone"], "Token": make_token(session["token_base"]), "ID": session["id"],
    })
    return data or []


def get_lessons(session: dict, club_id, http: requests.Session = None) -> list:
    data, _ = _authed(session, http, "GetClubLessonList", {
        "Token": make_token(session["token_base"]), "ID": session["id"],
        "ClubID": str(club_id), "Phone": session["phone"],
    })
    return data or []


def book(session: dict, club: dict, lesson: dict, http: requests.Session = None) -> str:
    """club = {club_id, terminal_id, bin_type}; lesson from get_lessons()."""
    _, message = _authed(session, http, "ClubOrder", {
        "Phone": session["phone"],
        "BinType": club["bin_type"],
        "LessonName": lesson["LessonName"],
        "IsCancelAllow": lesson.get("IsCancelAllow", False),
        "Token": make_token(session["token_base"]),
        "PreOrderDate": lesson["LessonStartDate"],
        "RboxLessonID": str(lesson["RboxLessonID"]),
        "ID": session["id"],
        "ClubID": str(club["club_id"]),
        "IsOnlyCheckWithoutTransaction": "false",
        "LessonStartDate": lesson["LessonStartDate"],
        "CancelationTime": fmt_float(lesson.get("CancelationTime")),
        "LessonEndDate": lesson["LessonEndDate"],
        "IsRbox": True,
        "CardNumber": session["card_number"],
        "IsSubscriptionOrder": "true",
        "TerminalID": str(club["terminal_id"]),
        "CoachName": lesson.get("CoachName", ""),
    })
    return message


def cancel(session: dict, order_num, http: requests.Session = None) -> str:
    _, message = _authed(session, http, "CancelClubOrder", {
        "Token": make_token(session["token_base"]), "Phone": session["phone"],
        "ClubOrderNum": str(order_num), "ID": session["id"],
    })
    return message
