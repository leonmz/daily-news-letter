"""
Telegram Bot - Command handlers and polling.

Supports commands: /start, /help, /digest, /movers, /watchlist
Runs daily digest via JobQueue at 10AM PT.
"""

import asyncio
import logging
from datetime import time as datetime_time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from main import format_compact_summary, format_for_telegram, generate_digest
from market_data import get_top_movers, enrich_sector_info, filter_movers_by_size

# Stores the last full digest per chat_id so the inline button can retrieve it
_last_full_digest: dict[int, str] = {}

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "<b>Available commands:</b>\n\n"
    "/digest - Generate full market digest (30-60s)\n"
    "/movers - Quick top movers summary\n"
    "/watchlist - Show current watchlist\n"
    "/watchlist add TICKER - Add ticker to watchlist\n"
    "/watchlist remove TICKER - Remove ticker\n"
    "/help - Show this help message"
)


# --- Authorization ---

def _is_authorized(update: Update) -> bool:
    """Check if the message is from the authorized chat."""
    chat = update.effective_chat
    return chat is not None and str(chat.id) == str(config.TELEGRAM_CHAT_ID)


async def _unauthorized_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Unauthorized.")


# --- Message helpers ---

async def _send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a long message, splitting into chunks with HTML formatting."""
    chunks = format_for_telegram(text)
    for chunk in chunks:
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def _send_digest_with_button(
    chat_id: int, full_digest: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send compact one-liner digest with an inline button for the full analysis.

    If no compact lines can be parsed (e.g. fallback template output), falls back
    to sending the full digest without a button.
    """
    compact = format_compact_summary(full_digest)

    if not compact:
        # Parsing failed — just send the full digest as-is
        await _send_long_message(chat_id, full_digest, context)
        return

    # Store full digest so the callback can retrieve it
    _last_full_digest[chat_id] = full_digest

    # Extract header line from full digest (first non-empty line)
    import html as _html
    import re
    raw_header = next(
        (line for line in full_digest.splitlines() if line.strip()), ""
    )
    # Strip leading markdown heading markers, then HTML-escape the text,
    # then wrap any **bold** spans in <b> tags.
    raw_header = re.sub(r"^#+\s*", "", raw_header)
    safe_header = _html.escape(raw_header)
    safe_header = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_header)

    # HTML-escape the compact lines (LLM-generated catalyst text may contain
    # characters like &, <, > that would break Telegram's HTML parse mode).
    safe_compact = _html.escape(compact)

    compact_message = f"{safe_header}\n\n{safe_compact}"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📊 View Full Analysis", callback_data="show_full_analysis")]]
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=compact_message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )


# --- Callback handlers ---

async def callback_show_full_analysis(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle 'show full analysis' button press — send stored full digest."""
    query = update.callback_query
    await query.answer()  # dismiss the loading spinner

    chat_id = query.message.chat_id
    full_digest = _last_full_digest.get(chat_id)

    if not full_digest:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Full analysis not available. Run /digest to generate a new one.",
        )
        return

    await _send_long_message(chat_id, full_digest, context)


# --- Command handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)
    await update.message.reply_text(
        "Market News Bot\n\n"
        "I send daily market digests at 10AM PT and respond to on-demand requests.\n\n"
        + HELP_TEXT,
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send a full digest on-demand (compact + button)."""
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)

    await update.message.reply_text("Generating digest... this may take 30-60 seconds.")
    try:
        digest = await asyncio.to_thread(generate_digest)
        await _send_digest_with_button(update.effective_chat.id, digest, context)
    except Exception as e:
        logger.exception("Failed to generate digest")
        await update.message.reply_text("Failed to generate digest. Check bot logs.")


async def cmd_movers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick top movers summary without LLM analysis."""
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)

    await update.message.reply_text("Fetching top movers...")
    try:
        movers = await asyncio.to_thread(
            lambda: filter_movers_by_size(enrich_sector_info(get_top_movers(10)))
        )

        lines = []
        for direction, label in [("gainers", "Top Gainers"), ("losers", "Top Losers")]:
            items = movers.get(direction, [])
            if not items:
                continue
            lines.append(f"<b>{label}</b>")
            for m in items[:5]:
                sign = "+" if m["change_pct"] > 0 else ""
                lines.append(
                    f"  {m['ticker']} {sign}{m['change_pct']:.1f}% "
                    f"(${m['price']:.2f})"
                )
            lines.append("")

        text = "\n".join(lines) if lines else "No movers data available."
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Failed to fetch movers")
        await update.message.reply_text("Failed to fetch movers. Check bot logs.")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show, add, or remove watchlist tickers."""
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)

    args = context.args or []

    if not args:
        if config.WATCHLIST:
            await update.message.reply_text(f"Watchlist: {', '.join(config.WATCHLIST)}")
        else:
            await update.message.reply_text("Watchlist is empty. Use /watchlist add TICKER")
        return

    action = args[0].lower()
    tickers = [t.upper() for t in args[1:] if t.isalpha() and 1 <= len(t) <= 5]

    if action == "add":
        if not tickers:
            await update.message.reply_text("Usage: /watchlist add TICKER [TICKER...]")
            return
        added = []
        for t in tickers:
            if t not in config.WATCHLIST and len(config.WATCHLIST) < 10:
                config.WATCHLIST.append(t)
                added.append(t)
        msg = f"Added: {', '.join(added)}\n" if added else "No new tickers added.\n"
        msg += f"Watchlist: {', '.join(config.WATCHLIST) or '(empty)'}"
        await update.message.reply_text(msg)

    elif action == "remove":
        if not tickers:
            await update.message.reply_text("Usage: /watchlist remove TICKER [TICKER...]")
            return
        removed = []
        for t in tickers:
            if t in config.WATCHLIST:
                config.WATCHLIST.remove(t)
                removed.append(t)
        msg = f"Removed: {', '.join(removed)}\n" if removed else "No tickers removed.\n"
        msg += f"Watchlist: {', '.join(config.WATCHLIST) or '(empty)'}"
        await update.message.reply_text(msg)

    else:
        await update.message.reply_text(
            "Usage:\n"
            "/watchlist - Show current list\n"
            "/watchlist add TICKER\n"
            "/watchlist remove TICKER"
        )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _unauthorized_reply(update, context)
    await update.message.reply_text("Unknown command. Try /help")


# --- Scheduled job ---

async def _scheduled_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: generate and send daily digest (compact + button)."""
    logger.info("Running scheduled daily digest")
    try:
        digest = await asyncio.to_thread(generate_digest)
        await _send_digest_with_button(int(config.TELEGRAM_CHAT_ID), digest, context)
        logger.info("Scheduled digest sent")
    except Exception as e:
        logger.exception("Scheduled digest failed: %s", e)


# --- Bot setup ---

def run_bot() -> None:
    """Start the Telegram bot with command handlers and daily schedule."""
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN.startswith("your_"):
        print("Error: TELEGRAM_BOT_TOKEN not configured in .env")
        return

    if not config.TELEGRAM_CHAT_ID:
        print("Error: TELEGRAM_CHAT_ID not configured in .env")
        return

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("movers", cmd_movers))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(callback_show_full_analysis, pattern="^show_full_analysis$"))

    # Schedule daily digest at 10:00 AM Pacific
    job_queue = app.job_queue
    target_time = datetime_time(
        hour=10, minute=0, second=0,
        tzinfo=ZoneInfo("America/Los_Angeles"),
    )
    job_queue.run_daily(_scheduled_digest, time=target_time, name="daily_digest")

    print("Bot started - listening for commands + daily digest at 10AM PT")
    print("Press Ctrl+C to stop\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
