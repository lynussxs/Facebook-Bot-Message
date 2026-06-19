"""
Messenger → Discord Forwarder Bot
Dùng fbchat-muqit (async) + Discord Webhook
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
FB_THREAD_ID = os.getenv("FB_THREAD_ID")
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "fb_cookies.json")

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
# Discord helper
# ---------------------------------------------------------------------------
DISCORD_COLOR = 0x5865F2  # Discord blurple

# Public Facebook Graph URL for profile pictures — no auth needed, returns redirect to CDN
def fb_avatar_url(uid: str) -> str:
    return f"https://graph.facebook.com/{uid}/picture?type=normal&width=128&height=128"


def send_discord(sender_name: str, text: str, dt: datetime, avatar_url: str = "") -> None:
    """Forward a message to the Discord webhook as a rich embed with avatar."""
    time_str = dt.strftime("%H:%M  %d/%m/%Y")

    author: dict = {"name": sender_name}
    if avatar_url:
        author["icon_url"] = avatar_url

    payload = {
        "embeds": [
            {
                "author": author,
                "description": text,
                "footer": {"text": f"🕐 {time_str}  •  Messenger"},
                "color": DISCORD_COLOR,
            }
        ]
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        resp.raise_for_status()
        preview = text[:60] + ("…" if len(text) > 60 else "")
        logger.info(f"✅  Forwarded [{sender_name}]: {preview}")
    except requests.RequestException as exc:
        logger.error(f"❌  Discord send failed: {exc}")


# ---------------------------------------------------------------------------
# Messenger Bot class — proper fbchat_muqit async API
# ---------------------------------------------------------------------------

class MessengerForwarder:
    """Wrapper that creates a fbchat_muqit.Client, registers event handlers, and runs."""

    def __init__(self):
        import fbchat_muqit as fbchat
        self._fbchat = fbchat
        self.client = fbchat.Client(cookies_file_path=COOKIES_FILE)
        self._own_uid: str = ""
        # Cache: uid → (name, avatar_url) to avoid repeated API calls
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
        """Return (display_name, avatar_url) for a sender UID.

        Tries fbchat_muqit fetchUserInfo first; always falls back to
        graph.facebook.com for the avatar so the icon is never missing.
        Results are cached per session.
        """
        if sender_id in self._user_cache:
            return self._user_cache[sender_id]

        name = sender_id          # fallback
        avatar = fb_avatar_url(sender_id)   # always works as a redirect

        try:
            # fetch_user_info returns Dict[str, User]
            info = await self.client.fetch_user_info(sender_id)
            user = (info or {}).get(sender_id)
            if user:
                # user.name is the full display name on Facebook
                if getattr(user, "name", ""):
                    name = user.name
                # user.image is Value (subclass of str) → the big profile picture URL
                if getattr(user, "image", None):
                    avatar = str(user.image)
        except Exception as exc:
            logger.debug(f"fetch_user_info failed for {sender_id}: {exc} — using Graph API fallback")

        self._user_cache[sender_id] = (name, avatar)
        return name, avatar

    async def _handle_message(self, event_data) -> None:
        try:
            thread_id = str(getattr(event_data, "thread_id", ""))
            sender_id = str(getattr(event_data, "sender_id", ""))

            # Only handle the target thread
            if thread_id != str(FB_THREAD_ID):
                return

            # Skip own messages
            if sender_id and sender_id == self._own_uid:
                return

            # Text content
            text = getattr(event_data, "text", None) or "[Sticker / Media / File]"

            # Sender name + avatar (cached after first lookup)
            sender_name, avatar_url = await self._resolve_user(sender_id)

            # Timestamp
            raw_ts = getattr(event_data, "timestamp", None)
            if raw_ts:
                try:
                    dt = datetime.fromtimestamp(int(raw_ts) / 1000)
                except (ValueError, OSError, TypeError):
                    dt = datetime.now()
            else:
                dt = datetime.now()

            logger.info(f"📩  [{sender_name}]: {text[:80]}")
            send_discord(sender_name, text, dt, avatar_url)

        except Exception as exc:
            logger.error(f"❌  Error handling message: {exc}", exc_info=True)

    async def run(self) -> None:
        async with self.client as c:
            self._own_uid = c.uid
            logger.info(f"✅  Logged in — UID: {c.uid} | Name: {c.name}")
            logger.info(f"🎯  Watching thread: {FB_THREAD_ID}")
            logger.info("📡  Listening for messages… (Ctrl+C to stop)")
            await c.listen()


# ---------------------------------------------------------------------------
# Main loop with exponential-backoff retry
# ---------------------------------------------------------------------------
INITIAL_RETRY_DELAY = 20
MAX_RETRY_DELAY = 300


async def main() -> None:
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    if not os.path.isfile(COOKIES_FILE):
        logger.error(
            f"❌  Cookie file not found: {COOKIES_FILE}\n"
            "    Follow the README to export your Facebook cookies first."
        )
        sys.exit(1)

    retry_delay = INITIAL_RETRY_DELAY

    while True:
        try:
            logger.info("🚀  Starting Messenger → Discord bot…")
            bot = MessengerForwarder()
            await bot.run()
            logger.warning("🔄  Listener returned — restarting immediately…")
            retry_delay = INITIAL_RETRY_DELAY

        except KeyboardInterrupt:
            logger.info("🛑  Stopped by user.")
            break

        except SystemExit:
            raise

        except Exception as exc:
            logger.error(f"💥  Bot crashed: {exc}")
            logger.info(f"🔄  Reconnecting in {retry_delay}s…")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
