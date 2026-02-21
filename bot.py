import json
import logging
import os
import re
from pathlib import Path

import aiohttp
import discord
from discord.ext import tasks


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = env_int("CHANNEL_ID", 0)
URL = os.getenv("CHECK_URL", "https://www.heroscroll.com/")
CHECK_EVERY_MIN = max(1, env_int("CHECK_EVERY_MIN", 30))
STATE_PATH = Path(os.getenv("STATE_PATH", "data/state.json"))
MENTION_EVERYONE = env_bool("MENTION_EVERYONE", True)
DEBUG_DUMPS = env_bool("DEBUG_DUMPS", False)

RE_TOTAL = re.compile(r"Total\s+Kingdoms\s*:\s*(\d+)", re.IGNORECASE)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    # Disable br to avoid corrupted output when brotli is not handled by proxy.
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("rok-bot")

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def write_debug_dump(filename: str, text: str) -> None:
    if not DEBUG_DUMPS:
        return
    dump_path = STATE_PATH.parent / filename
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump_path.write_text(text, encoding="utf-8", errors="ignore")
    logger.info("Saved debug dump: %s", dump_path)


def load_last_total() -> int | None:
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return int(data.get("last_total"))
    except Exception as exc:
        logger.warning("Failed to load state from %s: %s", STATE_PATH, exc)
        return None


def save_last_total(n: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_total": n}, ensure_ascii=False),
        encoding="utf-8",
    )


async def fetch_total_kingdoms(session: aiohttp.ClientSession) -> int:
    async def get(url: str) -> tuple[int, dict[str, str], str]:
        async with session.get(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as response:
            text = await response.text(errors="ignore")
            return response.status, dict(response.headers), text

    status, headers, text = await get(URL)
    text_norm = text.replace("\xa0", " ")
    logger.info(
        "Fetch: %s | HTTP %s | enc=%s | type=%s | len=%s",
        URL,
        status,
        headers.get("Content-Encoding", ""),
        headers.get("Content-Type", ""),
        len(text_norm),
    )

    match = RE_TOTAL.search(text_norm)

    # If main source changed, try fallback through Jina Reader.
    if (status != 200 or not match) and not URL.startswith("https://r.jina.ai/"):
        fallback = f"https://r.jina.ai/{URL}"
        status2, headers2, text2 = await get(fallback)
        text2_norm = text2.replace("\xa0", " ")
        logger.info(
            "Fetch: %s | HTTP %s | enc=%s | type=%s | len=%s",
            fallback,
            status2,
            headers2.get("Content-Encoding", ""),
            headers2.get("Content-Type", ""),
            len(text2_norm),
        )

        match2 = RE_TOTAL.search(text2_norm)
        if status2 == 200 and match2:
            return int(match2.group(1))

        write_debug_dump("last_page_main.html", text_norm)
        write_debug_dump("last_page_fallback.html", text2_norm)
        raise RuntimeError("Could not parse 'Total Kingdoms' from source and fallback.")

    if status != 200 or not match:
        write_debug_dump("last_page_main.html", text_norm)
        raise RuntimeError("Could not parse 'Total Kingdoms' from source.")

    return int(match.group(1))


async def resolve_channel() -> discord.abc.Messageable | None:
    channel = client.get_channel(CHANNEL_ID)
    if channel is not None:
        return channel

    try:
        return await client.fetch_channel(CHANNEL_ID)
    except Exception as exc:
        logger.error("Unable to access channel %s: %s", CHANNEL_ID, exc)
        return None


@tasks.loop(minutes=CHECK_EVERY_MIN)
async def check_loop() -> None:
    channel = await resolve_channel()
    if channel is None:
        logger.error("Channel is unavailable. Check CHANNEL_ID and bot permissions.")
        return

    async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
        try:
            current = await fetch_total_kingdoms(session)
        except Exception as exc:
            logger.error("Check failed: %s", exc)
            return

    last = load_last_total()

    # First run stores current value to avoid false notifications.
    if last is None:
        save_last_total(current)
        logger.info("Initial state saved: Total Kingdoms = %s", current)
        return

    if current <= last:
        logger.info("No changes: %s", current)
        return

    new_ids = list(range(last + 1, current + 1))
    save_last_total(current)

    if len(new_ids) == 1:
        body = f"New kingdom released: **#{new_ids[0]}**"
    else:
        ids = ", ".join(f"**#{x}**" for x in new_ids)
        body = f"New kingdoms released: {ids}"

    prefix = "@everyone " if MENTION_EVERYONE else ""
    message = f"{prefix}🆕 {body}\nSource: {URL}"
    allowed_mentions = discord.AllowedMentions(everyone=MENTION_EVERYONE)

    await channel.send(message, allowed_mentions=allowed_mentions)
    logger.info("Notification sent: %s", body)


@client.event
async def on_ready() -> None:
    logger.info("Logged in as %s | check every %s min", client.user, CHECK_EVERY_MIN)
    if not check_loop.is_running():
        check_loop.start()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set")
    if CHANNEL_ID <= 0:
        raise SystemExit("CHANNEL_ID is not set or invalid")

    client.run(TOKEN)
