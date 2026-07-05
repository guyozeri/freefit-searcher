#!/usr/bin/env python3
"""
FreeFit Telegram bot.

Each Telegram user logs into their OWN FreeFit account (phone -> SMS code); the
bot stores their device token in bot_sessions.json (gitignored) and books on
their behalf. Built on freefit_client.py.

Commands:
    /login          log in with your phone number + SMS code
    /logout         forget your saved login
    /mybookings     your upcoming bookings (with cancel buttons)
    /clubs <query>  search clubs by name/area (tap one to see its lessons)
    /lessons <id>   list a club's lessons (with book buttons)
    /help

Run:
    export TELEGRAM_BOT_TOKEN=123456:ABC...       # from @BotFather
    python bot.py
Requires output/clubs_api.json (run `python fetch_clubs.py` once) for club search.
"""

import asyncio
import json
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters,
)

import freefit_client as ff

SESSIONS_PATH = Path(__file__).parent / "bot_sessions.json"
ASK_PHONE, ASK_CODE = range(2)
MAX_CLUB_RESULTS = 12
MAX_LESSONS = 15


# ---- per-user session storage --------------------------------------------

def _load_sessions() -> dict:
    if SESSIONS_PATH.exists():
        return json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_sessions(sessions: dict):
    SESSIONS_PATH.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


SESSIONS = _load_sessions()          # {telegram_user_id(str): freefit_session}
HTTP = {}                            # {telegram_user_id(str): requests.Session} (cookie isolation)


def _uid(update: Update) -> str:
    return str(update.effective_user.id)


def _session_of(update: Update):
    return SESSIONS.get(_uid(update))


def _http_of(update: Update):
    uid = _uid(update)
    if uid not in HTTP:
        HTTP[uid] = ff.new_http()
    return HTTP[uid]


# ---- helpers --------------------------------------------------------------

async def _require_login(update: Update) -> bool:
    if _session_of(update):
        return True
    await update.effective_message.reply_text("Please /login first.")
    return False


def _lesson_line(l: dict) -> str:
    tag = ""
    if l.get("IsUserBooked"):
        tag = " ✅ booked"
    elif l.get("IsLessonFull"):
        tag = " ⛔ full"
    elif l.get("SlotsAvailable") is not None:
        tag = f" ({l['SlotsAvailable']} spots)"
    return f"{l.get('LessonStartDate','?')} · {l.get('LessonName','')}{tag}"


# ---- /login conversation --------------------------------------------------

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me your FreeFit phone number (e.g. 0521234567). Send /cancel to abort.")
    return ASK_PHONE


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not (phone.startswith("0") and phone[1:].isdigit() and 9 <= len(phone) <= 10):
        await update.message.reply_text("That doesn't look like a phone number. Try again, e.g. 0521234567.")
        return ASK_PHONE
    context.user_data["phone"] = phone
    try:
        await asyncio.to_thread(ff.send_sms_code, phone, _http_of(update))
    except Exception as e:
        await update.message.reply_text(f"Couldn't send a code: {e}\nTry /login again.")
        return ConversationHandler.END
    await update.message.reply_text("Sent! Now send me the SMS code.")
    return ASK_CODE


async def login_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    phone = context.user_data.get("phone")
    try:
        session = await asyncio.to_thread(
            ff.verify_and_login, phone, code, http=_http_of(update))
    except Exception as e:
        await update.message.reply_text(f"Login failed: {e}\nSend the code again, or /login to restart.")
        return ASK_CODE
    SESSIONS[_uid(update)] = session
    _save_sessions(SESSIONS)
    name = session.get("first_name") or phone
    await update.message.reply_text(
        f"Logged in as {name} ✅\nTry /clubs <name>, /mybookings, or /lessons <clubId>.")
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Login cancelled.")
    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SESSIONS.pop(_uid(update), None)
    HTTP.pop(_uid(update), None)
    _save_sessions(SESSIONS)
    await update.message.reply_text("Logged out. Your saved login was removed.")


# ---- /help ----------------------------------------------------------------

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "FreeFit bot commands:\n"
        "/login — log in with phone + SMS code\n"
        "/logout — forget your login\n"
        "/mybookings — your upcoming bookings\n"
        "/clubs <query> — search clubs (tap one for its lessons)\n"
        "/lessons <clubId> — a club's lessons, with book buttons")


# ---- /mybookings ----------------------------------------------------------

async def mybookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_login(update):
        return
    try:
        orders = await asyncio.to_thread(ff.get_orders, _session_of(update), _http_of(update))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    if not orders:
        await update.message.reply_text("You have no upcoming bookings.")
        return
    for o in orders:
        text = f"{o.get('SupplyDate','?')} · {o.get('LessonName','')}\n{o.get('ClubName','')}"
        kb = None
        if o.get("IsCancelAllow"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"cancel:{o['ID']}")]])
        await update.message.reply_text(text, reply_markup=kb)


# ---- /clubs ---------------------------------------------------------------

async def clubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /clubs <name or area>, e.g. /clubs BINENFIT")
        return
    session = _session_of(update) or {}
    try:
        matches = await asyncio.to_thread(ff.search_clubs, session, query, MAX_CLUB_RESULTS, _http_of(update))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}\n(If club data isn't cached, run fetch_clubs.py.)")
        return
    if not matches:
        await update.message.reply_text(f"No clubs matching '{query}'.")
        return
    rows = [[InlineKeyboardButton(
        f"{(c.get('Name') or '').strip()} — {(c.get('AreaName') or '').strip()}"[:60],
        callback_data=f"club:{c['RecordID']}")] for c in matches]
    await update.message.reply_text(
        f"{len(matches)} club(s) for '{query}' — tap one to see lessons:",
        reply_markup=InlineKeyboardMarkup(rows))


# ---- /lessons + booking ---------------------------------------------------

async def _show_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE, club_id: str, reply_to):
    session = _session_of(update)
    http = _http_of(update)
    try:
        lessons = await asyncio.to_thread(ff.get_lessons, session, club_id, http)
    except Exception as e:
        await reply_to(f"Error: {e}")
        return
    if not lessons:
        await reply_to("No upcoming lessons for this club.")
        return
    shown = lessons[:MAX_LESSONS]
    rows = []
    for l in shown:
        if not l.get("IsUserBooked") and not l.get("IsLessonFull"):
            # Identify the lesson by its stable RboxLessonID, not a list position:
            # buttons on old messages stay tappable and the list can reorder.
            rows.append([InlineKeyboardButton(
                "Book · " + _lesson_line(l)[:55], callback_data=f"book:{club_id}:{l['RboxLessonID']}")])
    body = "\n".join(_lesson_line(l) for l in shown)
    if len(lessons) > MAX_LESSONS:
        body += f"\n… and {len(lessons) - MAX_LESSONS} more"
    await reply_to(body, reply_markup=InlineKeyboardMarkup(rows) if rows else None)


async def lessons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_login(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /lessons <clubId> (get the id from /clubs)")
        return
    await _show_lessons(update, context, context.args[0], update.message.reply_text)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _session_of(update):
        await q.message.reply_text("Please /login first.")
        return
    data = q.data or ""

    if data.startswith("club:"):
        await _show_lessons(update, context, data.split(":", 1)[1], q.message.reply_text)

    elif data.startswith("book:"):
        _, club_id, rbox_id = data.split(":")
        session, http = _session_of(update), _http_of(update)
        try:
            club = await asyncio.to_thread(ff.find_club, session, club_id, http)
            if not club or not club.get("terminal_id"):
                await q.message.reply_text("This club isn't bookable through the bot.")
                return
            # Re-fetch the current schedule and match by id, so a tapped button
            # always books exactly the lesson it names (never a stale position).
            lessons = await asyncio.to_thread(ff.get_lessons, session, club_id, http)
            lesson = next((l for l in lessons if str(l["RboxLessonID"]) == rbox_id), None)
            if not lesson:
                await q.message.reply_text("That lesson is no longer available — run /lessons again.")
                return
            msg = await asyncio.to_thread(ff.book, session, club, lesson, http)
            await q.message.reply_text(f"✅ Booked {lesson.get('LessonName','')} on {lesson.get('LessonStartDate','')}.\n{msg}")
        except Exception as e:
            await q.message.reply_text(f"Couldn't book: {e}")

    elif data.startswith("cancel:"):
        order_num = data.split(":", 1)[1]
        try:
            msg = await asyncio.to_thread(ff.cancel, _session_of(update), order_num, _http_of(update))
            await q.message.reply_text(f"Cancelled. {msg}")
        except Exception as e:
            await q.message.reply_text(f"Couldn't cancel: {e}")


# ---- wiring ---------------------------------------------------------------

def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_code)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    ))
    app.add_handler(CommandHandler(["start", "help"], help_cmd))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("mybookings", mybookings))
    app.add_handler(CommandHandler("clubs", clubs))
    app.add_handler(CommandHandler("lessons", lessons_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (get one from @BotFather).")
    print("FreeFit bot running. Press Ctrl+C to stop.")
    build_app(token).run_polling()


if __name__ == "__main__":
    main()
