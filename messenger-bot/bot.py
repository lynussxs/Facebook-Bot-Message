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
FB_EMAIL = os.getenv("FB_EMAIL")
FB_PASSWORD = os.getenv("FB_PASSWORD")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
FB_THREAD_ID = os.getenv("FB_THREAD_ID")

missing = [k for k, v in {
    "FB_EMAIL": FB_EMAIL,
    "FB_PASSWORD": FB_PASSWORD,
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
DISCORD_COLOR = 0x5865F2  # blurple


def send_discord(sender_name: str, text: str, dt: datetime) -> None:
    """Forward a single message to the Discord webhook as an embed."""
    time_str = dt.strftime("%H:%M  %d/%m/%Y")
    payload = {
        "embeds": [
            {
                "author": {"name": sender_name},
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
        logger.info(f"✅  Forwarded  [{sender_name}]: {preview}")
    except requests.RequestException as exc:
        logger.error(f"❌  Discord send failed: {exc}")


# ---------------------------------------------------------------------------
# Messenger bot (fbchat-muqit)
# ---------------------------------------------------------------------------

def build_listener_class():
    """
    Dynamically create the listener subclass *after* fbchat is imported.
    This keeps the import error contained to run_bot().
    """
    import fbchat  # noqa: PLC0415

    class MessengerBot(fbchat.Client):
        def onMessage(
            self,
            author_id,
            message_object,
            thread_id,
            thread_type,
            **kwargs,
        ):
            # Only handle the target group thread
            if str(thread_id) != str(FB_THREAD_ID):
                return

            # Skip own messages
            if str(author_id) == str(self.uid):
                return

            # Resolve sender name
            try:
                info = self.fetchUserInfo(author_id)
                user = info.get(str(author_id))
                if user:
                    sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                else:
                    sender_name = f"UID {author_id}"
            except Exception:
                sender_name = f"UID {author_id}"

            # Text content
            text = message_object.text or "[Sticker / Media / File]"

            # Timestamp (fbchat returns ms since epoch)
            raw_ts = getattr(message_object, "timestamp", None)
            if raw_ts:
                try:
                    dt = datetime.fromtimestamp(int(raw_ts) / 1000)
                except (ValueError, OSError):
                    dt = datetime.now()
            else:
                dt = datetime.now()

            logger.info(f"📩  [{sender_name}]: {text[:80]}")
            send_discord(sender_name, text, dt)

        def onConnectionError(self, exception, **kwargs):
            logger.warning(f"⚠️   Connection error: {exception}")

        def onLoggedOut(self, reason, **kwargs):
            logger.warning(f"⚠️   Logged out — reason: {reason}")

    return MessengerBot


def run_bot() -> None:
    """
    Login to Facebook and start long-polling.
    Raises on unrecoverable errors so the outer retry loop can restart.
    """
    import fbchat  # noqa: PLC0415

    BotClass = build_listener_class()

    logger.info("🔑  Logging in to Facebook…")
    try:
        bot = BotClass(FB_EMAIL, FB_PASSWORD)
    except fbchat.FBchatUserError as exc:
        logger.error(f"❌  Login failed (check credentials / checkpoint): {exc}")
        raise
    except fbchat.FBchatException as exc:
        logger.error(f"❌  Facebook error during login: {exc}")
        raise

    logger.info(f"✅  Logged in — UID: {bot.uid}")
    logger.info(f"🎯  Watching thread: {FB_THREAD_ID}")
    logger.info("📡  Listening for messages… (Ctrl+C to stop)")

    try:
        bot.listen()
    finally:
        try:
            bot.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Async main with exponential-backoff retry
# ---------------------------------------------------------------------------
INITIAL_RETRY_DELAY = 15   # seconds
MAX_RETRY_DELAY = 300      # 5 minutes cap


async def main() -> None:
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        logger.error("Set them in the Replit Secrets panel and restart the workflow.")
        sys.exit(1)

    loop = asyncio.get_event_loop()
    retry_delay = INITIAL_RETRY_DELAY

    while True:
        try:
            logger.info("🚀  Starting Messenger → Discord bot…")
            # run_bot() is blocking — offload to a thread executor
            await loop.run_in_executor(None, run_bot)
            # If listen() returns cleanly, restart immediately
            logger.warning("🔄  Listener exited — restarting…")
            retry_delay = INITIAL_RETRY_DELAY

        except KeyboardInterrupt:
            logger.info("🛑  Stopped by user.")
            break

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
