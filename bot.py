import os
import re
import asyncio
import logging

import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r'https?://[^\s<>"\']+')
TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_LINKS_PER_MESSAGE = 20


async def check_url(session: aiohttp.ClientSession, url: str) -> dict:
    """Check a single URL, trying HEAD first then falling back to GET."""
    try:
        async with session.head(url, allow_redirects=True, timeout=TIMEOUT) as resp:
            status = resp.status
            if status >= 400:
                async with session.get(url, allow_redirects=True, timeout=TIMEOUT) as resp2:
                    status = resp2.status
            return {"url": url, "status": status, "ok": status < 400, "error": None}
    except Exception:
        try:
            async with session.get(url, allow_redirects=True, timeout=TIMEOUT) as resp:
                status = resp.status
                return {"url": url, "status": status, "ok": status < 400, "error": None}
        except Exception as e2:
            return {"url": url, "status": None, "ok": False, "error": str(e2)}


async def check_urls(urls: list) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BrokenLinkCheckerBot/1.0)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [check_url(session, u) for u in urls]
        return await asyncio.gather(*tasks)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm Broken Link Checker.\n\n"
        "Send me one or more links in a message and I'll tell you whether "
        "each one is alive or broken.\n\n"
        "Commands:\n"
        "/check <url> - check a single URL\n"
        "/help - show this message"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /check https://example.com")
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    await handle_urls(update, [url])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = URL_REGEX.findall(text)
    if not urls:
        await update.message.reply_text(
            "I couldn't find any links in that message. "
            "Send me a URL starting with http:// or https://"
        )
        return
    await handle_urls(update, urls)


async def handle_urls(update: Update, urls: list):
    urls = list(dict.fromkeys(urls))  # dedupe, preserve order
    truncated_notice = ""
    if len(urls) > MAX_LINKS_PER_MESSAGE:
        truncated_notice = f"\n(Only checking the first {MAX_LINKS_PER_MESSAGE} links.)"
        urls = urls[:MAX_LINKS_PER_MESSAGE]

    status_msg = await update.message.reply_text(f"🔍 Checking {len(urls)} link(s)...")
    results = await check_urls(urls)

    lines = []
    broken_count = 0
    for r in results:
        if r["ok"]:
            lines.append(f"✅ {r['status']} - {r['url']}")
        else:
            broken_count += 1
            if r["error"]:
                lines.append(f"❌ ERROR - {r['url']}\n    ({r['error'][:80]})")
            else:
                lines.append(f"❌ {r['status']} - {r['url']}")

    summary = f"\n\nChecked {len(urls)} link(s): {len(urls) - broken_count} OK, {broken_count} broken."
    text = "\n".join(lines) + summary + truncated_notice
    if len(text) > 4000:
        text = text[:3900] + "\n...(truncated)"

    await status_msg.edit_text(text)


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting (polling mode)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
