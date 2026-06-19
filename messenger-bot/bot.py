"""
Messenger → Discord Forwarder Bot
Dùng fbchat-muqit (async) + Discord Webhook + Discord Bot (2-way)
"""

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

import requests
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

# ---------------------------------------------------------------------------
# Web Server (Flask) — keeps Railway happy, serves health-check endpoint
# ---------------------------------------------------------------------------
_flask_app = Flask(__name__)

@_flask_app.get("/")
def _index():
    return "Facebook Bot is Running", 200

@_flask_app.get("/health")
def _health():
    return {"status": "ok"}, 200

def _start_web_server() -> None:
    port = int(os.environ.get("PORT", 3000))
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    _flask_app.run(host="0.0.0.0", port=port)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")       # optional — Discord bot token
FB_THREAD_ID    = os.getenv("FB_THREAD_ID")
COOKIES_FILE    = os.path.join(os.path.dirname(__file__), "fb_cookies.json")

missing = [k for k, v in {
    "DISCORD_WEBHOOK": DISCORD_WEBHOOK,
    "FB_THREAD_ID": FB_THREAD_ID,
}.items() if not v]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S %d/%m/%Y",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("messenger-bot")

# ---------------------------------------------------------------------------
# Shared Facebook client reference — set once FB bot logs in
# ---------------------------------------------------------------------------
_fb_client = None   # fbchat_muqit.Client instance, set by MessengerForwarder.run()

# ---------------------------------------------------------------------------
# Discord Command Bot — !sendfb <fb_thread_id> <message>
# ---------------------------------------------------------------------------
_discord_bot = None

def _build_discord_bot():
    """Build and return a discord.ext.commands.Bot. Returns None if discord.py unavailable."""
    try:
        import discord
        from discord.ext import commands
    except ImportError:
        logger.warning("discord.py not installed — Discord command bot disabled.")
        return None

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info(f"🤖  Discord command bot ready — logged in as {bot.user}")

    @bot.command(name="sendfb")
    async def sendfb(ctx, fb_id: str, *, message: str):
        """Send a message to a Facebook thread via the logged-in FB account.

        Usage:  !sendfb <facebook_thread_id> <message text>
        """
        if _fb_client is None:
            await ctx.reply("❌ Facebook bot chưa kết nối, thử lại sau.")
            return
        try:
            await _fb_client.send_message(message, thread_id=fb_id)
            await ctx.reply(f"✅ Đã gửi đến FB `{fb_id}`: {message[:80]}")
            logger.info(f"📤  [Discord→FB] thread={fb_id}  msg={message[:60]}")
        except Exception as exc:
            logger.error(f"❌  sendfb failed: {exc}")
            await ctx.reply(f"❌ Gửi thất bại: {exc}")

    @bot.command(name="ping")
    async def ping(ctx):
        await ctx.reply("🏓 Pong! Bot đang sống.")

    return bot

# ---------------------------------------------------------------------------
# Discord Webhook helper (forward Messenger → Discord)
# ---------------------------------------------------------------------------

def fb_avatar_url(uid: str) -> str:
    return f"https://graph.facebook.com/{uid}/picture?type=normal&width=128&height=128"


def _download(url: str) -> bytes | None:
    """Download a URL and return bytes, or None on failure."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.content
    except Exception as exc:
        logger.debug(f"Download failed ({url[:60]}…): {exc}")
        return None


def send_discord(
    sender_name: str,
    text: str,
    dt: datetime,
    avatar_url: str = "",
    attachments: list[tuple[str, str, str]] | None = None,
) -> None:
    """Forward a message using webhook impersonation."""
    time_str = dt.strftime("%H:%M  %d/%m/%Y")
    footer = f"-# 🕐 {time_str}  •  Messenger"

    base_payload: dict = {
        "username": sender_name,
        "avatar_url": avatar_url or fb_avatar_url("0"),
    }

    files: dict = {}
    failed_labels: list[str] = []

    for i, (url, filename, label) in enumerate(attachments or []):
        data = _download(url) if url else None
        if data:
            files[f"files[{i}]"] = (filename, data)
        else:
            failed_labels.append(label)

    content_parts: list[str] = []
    if text:
        content_parts.append(text)
    if failed_labels:
        content_parts.append("  ".join(failed_labels))
    content_parts.append(footer)
    base_payload["content"] = "\n".join(content_parts)

    try:
        if files:
            resp = requests.post(
                DISCORD_WEBHOOK,
                data={"payload_json": json.dumps(base_payload)},
                files=files,
                timeout=30,
            )
        else:
            resp = requests.post(DISCORD_WEBHOOK, json=base_payload, timeout=10)

        resp.raise_for_status()
        preview = (text or str(attachments))[:60]
        logger.info(f"✅  Forwarded [{sender_name}]: {preview}")
    except requests.RequestException as exc:
        logger.error(f"❌  Discord send failed: {exc}")


# ---------------------------------------------------------------------------
# Messenger Bot class
# ---------------------------------------------------------------------------

class MessengerForwarder:

    def __init__(self):
        import fbchat_muqit as fbchat
        self._fbchat = fbchat
        self.client = fbchat.Client(cookies_file_path=COOKIES_FILE)
        self._own_uid: str = ""
        self._user_cache: dict[str, tuple[str, str]] = {}
        self._register_handlers()

    def _register_handlers(self):
        fbchat = self._fbchat
        client = self.client

        @client.event(fbchat.EventType.MESSAGE)
        async def on_message(event_data: fbchat.Message):
            await self._handle_message(event_data)

        @client.event(fbchat.EventType.DISCONNECT)
        async def on_disconnect():
            logger.warning("⚠️   Disconnected from Messenger MQTT")

        @client.event(fbchat.EventType.RECONNECT)
        async def on_reconnect():
            logger.info("🔄  Reconnected to Messenger MQTT")

    async def _resolve_user(self, sender_id: str) -> tuple[str, str]:
        if sender_id in self._user_cache:
            return self._user_cache[sender_id]

        name = sender_id
        avatar = fb_avatar_url(sender_id)

        try:
            info = await self.client.fetch_user_info(sender_id)
            user = (info or {}).get(sender_id)
            if user:
                if getattr(user, "name", ""):
                    name = user.name
                if getattr(user, "image", None):
                    avatar = str(user.image)
        except Exception as exc:
            logger.debug(f"fetch_user_info failed for {sender_id}: {exc}")

        self._user_cache[sender_id] = (name, avatar)
        return name, avatar

    @staticmethod
    def _extract_attachments(event_data) -> list[tuple[str, str, str]]:
        from fbchat_muqit.models.attachment import (
            ImageAttachment, VideoAttachment, GifAttachment,
            StickerAttachment, AudioAttachment, FileAttachment,
        )

        def _ensure_ext(name: str, ext: str) -> str:
            return name if name.lower().endswith(ext) else name + ext

        raw = getattr(event_data, "attachments", None) or []
        result = []
        for att in raw:
            if att is None:
                continue
            try:
                logger.debug(f"Attachment: {type(att).__name__}")

                if isinstance(att, ImageAttachment):
                    url = att.large_preview.url or att.thumbnail.url
                    fname = _ensure_ext(att.filename or "image", ".jpg")
                    result.append((url, fname, "📷 [Hình ảnh]"))

                elif isinstance(att, VideoAttachment):
                    fname = _ensure_ext(att.filename or "video", ".mp4")
                    result.append((att.playable_url, fname, "🎥 [Video]"))

                elif isinstance(att, GifAttachment):
                    url = att.animated_image.url
                    fname = _ensure_ext(att.filename or "animation", ".gif")
                    result.append((url, fname, "🎞️ [GIF]"))

                elif isinstance(att, StickerAttachment):
                    result.append((att.url, "sticker.webp", "😄 [Sticker]"))

                elif isinstance(att, AudioAttachment):
                    fname = _ensure_ext(att.filename or "audio", ".mp3")
                    result.append((att.playable_url, fname, "🎵 [Audio]"))

                elif isinstance(att, FileAttachment):
                    fname = att.filename if (hasattr(att, "filename") and att.filename) else "file"
                    result.append((att.download_url or "", fname, "📎 [File]"))

                else:
                    logger.debug(f"Unknown attachment type skipped: {type(att).__name__}")

            except Exception as exc:
                logger.debug(f"Could not extract attachment {type(att).__name__}: {exc}")
        return result

    async def _handle_message(self, event_data) -> None:
        try:
            thread_id = str(getattr(event_data, "thread_id", ""))
            sender_id = str(getattr(event_data, "sender_id", ""))

            if thread_id != str(FB_THREAD_ID):
                return

            if sender_id and sender_id == self._own_uid:
                return

            text = getattr(event_data, "text", None) or ""
            attachments = self._extract_attachments(event_data)

            if not text and not attachments:
                return

            sender_name, avatar_url = await self._resolve_user(sender_id)

            raw_ts = getattr(event_data, "timestamp", None)
            if raw_ts:
                try:
                    dt = datetime.fromtimestamp(int(raw_ts) / 1000, tz=VN_TZ)
                except (ValueError, OSError, TypeError):
                    dt = datetime.now(tz=VN_TZ)
            else:
                dt = datetime.now(tz=VN_TZ)

            log_preview = text[:60] or f"{len(attachments)} attachment(s)"
            logger.info(f"📩  [{sender_name}]: {log_preview}")
            send_discord(sender_name, text, dt, avatar_url, attachments or None)

        except Exception as exc:
            logger.error(f"❌  Error handling message: {exc}", exc_info=True)

    async def run(self) -> None:
        global _fb_client
        async with self.client as c:
            _fb_client = c          # expose to Discord commands
            self._own_uid = c.uid
            logger.info(f"✅  Logged in — UID: {c.uid} | Name: {c.name}")
            logger.info(f"🎯  Watching thread: {FB_THREAD_ID}")
            logger.info("📡  Listening for messages… (Ctrl+C to stop)")
            await c.listen()
        _fb_client = None


# ---------------------------------------------------------------------------
# FB bot retry loop (runs forever, restarts on crash)
# ---------------------------------------------------------------------------
INITIAL_RETRY_DELAY = 20
MAX_RETRY_DELAY = 300


async def _run_fb_bot() -> None:
    retry_delay = INITIAL_RETRY_DELAY
    while True:
        try:
            logger.info("🚀  Starting Messenger → Discord forwarder…")
            bot = MessengerForwarder()
            await bot.run()
            logger.warning("🔄  FB listener returned — restarting…")
            retry_delay = INITIAL_RETRY_DELAY

        except (KeyboardInterrupt, SystemExit):
            raise

        except Exception as exc:
            logger.error(f"💥  FB bot crashed: {exc}")
            logger.info(f"🔄  Reconnecting in {retry_delay}s…")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    if not os.path.isfile(COOKIES_FILE):
        logger.error(
            f"❌  Cookie file not found: {COOKIES_FILE}\n"
            "    Export your Facebook cookies first (see README)."
        )
        sys.exit(1)

    # Flask health-check server in background thread
    web_thread = threading.Thread(target=_start_web_server, daemon=True)
    web_thread.start()
    logger.info(f"🌐  Web server started on port {os.environ.get('PORT', 3000)}")

    # Build Discord command bot (optional — only if DISCORD_TOKEN is set)
    tasks = [asyncio.create_task(_run_fb_bot())]

    if DISCORD_TOKEN:
        global _discord_bot
        _discord_bot = _build_discord_bot()
        if _discord_bot:
            tasks.append(asyncio.create_task(_discord_bot.start(DISCORD_TOKEN)))
            logger.info("🤖  Discord command bot starting…")
    else:
        logger.info("ℹ️   DISCORD_TOKEN not set — Discord command bot disabled.")

    try:
        await asyncio.gather(*tasks)
    finally:
        if _discord_bot and not _discord_bot.is_closed():
            await _discord_bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
