import asyncio
import json
import logging
import os
import re
from collections import Counter
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


def env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int_set(name: str) -> set[int]:
    values: set[int] = set()
    for raw in env_csv(name):
        try:
            values.add(int(raw))
        except ValueError:
            continue
    return values


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = env_int("CHANNEL_ID", 0)
CHECK_EVERY_MIN = max(1, env_int("CHECK_EVERY_MIN", 30))
CHECK_TIMEOUT_SEC = max(5, env_int("CHECK_TIMEOUT_SEC", 25))
STATE_PATH = Path(os.getenv("STATE_PATH", "data/state.json"))
MENTION_EVERYONE = env_bool("MENTION_EVERYONE", True)
DEBUG_DUMPS = env_bool("DEBUG_DUMPS", False)
MIN_SOURCE_AGREEMENT = max(1, env_int("MIN_SOURCE_AGREEMENT", 1))
MIN_KINGDOM_ID = env_int("MIN_KINGDOM_ID", 1000)
MAX_KINGDOM_ID = env_int("MAX_KINGDOM_ID", 9999)
WATCH_CHANNEL_IDS = env_int_set("WATCH_CHANNEL_IDS")

base_url = os.getenv("CHECK_URL", "https://heroscroll.com/")
CHECK_URLS = unique(env_csv("CHECK_URLS") or [base_url])

RE_TOTAL = re.compile(r"Total\s+Kingdoms\s*:\s*(\d+)", re.IGNORECASE)
DEFAULT_MESSAGE_PATTERNS = [
    r"\b(?:kingdom|kd)\s*#?\s*(\d{3,5})\b",
    r"\bnew\s+(?:kingdom|kd)\D{0,10}#?\s*(\d{3,5})\b",
]

custom_message_patterns = [x.strip() for x in os.getenv("MESSAGE_PATTERNS", "").split("||") if x.strip()]
message_patterns_raw = custom_message_patterns or DEFAULT_MESSAGE_PATTERNS
MESSAGE_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in message_patterns_raw]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
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
if WATCH_CHANNEL_IDS:
    intents.message_content = True
client = discord.Client(intents=intents)
state_lock = asyncio.Lock()


def sanitize_for_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return cleaned[:80] or "source"


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


def save_last_total(value: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_total": value}, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_total_kingdoms(text: str) -> int | None:
    match = RE_TOTAL.search(text)
    if not match:
        return None
    return int(match.group(1))


async def http_get(session: aiohttp.ClientSession, url: str) -> tuple[int, dict[str, str], str]:
    async with session.get(
        url,
        allow_redirects=True,
        timeout=aiohttp.ClientTimeout(total=CHECK_TIMEOUT_SEC),
    ) as response:
        text = await response.text(errors="ignore")
        return response.status, dict(response.headers), text.replace("\xa0", " ")


async def fetch_total_from_source(session: aiohttp.ClientSession, url: str) -> int:
    status, headers, text = await http_get(session, url)
    logger.info(
        "Fetch: %s | HTTP %s | enc=%s | type=%s | len=%s",
        url,
        status,
        headers.get("Content-Encoding", ""),
        headers.get("Content-Type", ""),
        len(text),
    )

    parsed = parse_total_kingdoms(text)
    if status == 200 and parsed is not None:
        return parsed

    if not url.startswith("https://r.jina.ai/"):
        fallback = f"https://r.jina.ai/{url}"
        status2, headers2, text2 = await http_get(session, fallback)
        logger.info(
            "Fetch: %s | HTTP %s | enc=%s | type=%s | len=%s",
            fallback,
            status2,
            headers2.get("Content-Encoding", ""),
            headers2.get("Content-Type", ""),
            len(text2),
        )
        parsed2 = parse_total_kingdoms(text2)
        if status2 == 200 and parsed2 is not None:
            return parsed2

        source_tag = sanitize_for_filename(url)
        write_debug_dump(f"{source_tag}_main.html", text)
        write_debug_dump(f"{source_tag}_fallback.html", text2)
        raise RuntimeError(f"Could not parse 'Total Kingdoms' from source and fallback: {url}")

    source_tag = sanitize_for_filename(url)
    write_debug_dump(f"{source_tag}_main.html", text)
    raise RuntimeError(f"Could not parse 'Total Kingdoms' from source: {url}")


def select_total_value(values: list[int]) -> int:
    if MIN_SOURCE_AGREEMENT <= 1:
        return max(values)

    counts = Counter(values)
    eligible = [value for value, count in counts.items() if count >= MIN_SOURCE_AGREEMENT]
    if eligible:
        return max(eligible)

    best = max(values)
    logger.warning(
        "No source consensus reached (MIN_SOURCE_AGREEMENT=%s). Using max value=%s.",
        MIN_SOURCE_AGREEMENT,
        best,
    )
    return best


async def fetch_total_kingdoms(session: aiohttp.ClientSession) -> tuple[int, list[str]]:
    successes: list[tuple[str, int]] = []
    failures: list[str] = []

    for url in CHECK_URLS:
        try:
            total = await fetch_total_from_source(session, url)
            successes.append((url, total))
        except Exception as exc:
            failures.append(f"{url}: {exc}")

    if not successes:
        raise RuntimeError(f"All web sources failed. Errors: {'; '.join(failures)}")

    selected_value = select_total_value([value for _, value in successes])
    selected_sources = [source for source, value in successes if value == selected_value]
    logger.info(
        "Web totals: %s | selected=%s",
        ", ".join(f"{source}={value}" for source, value in successes),
        selected_value,
    )

    if failures:
        logger.warning("Web source failures: %s", "; ".join(failures))

    return selected_value, selected_sources


def extract_candidates(text: str) -> list[int]:
    found: set[int] = set()
    for pattern in MESSAGE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if MIN_KINGDOM_ID <= value <= MAX_KINGDOM_ID:
                found.add(value)
    return sorted(found)


def message_to_text(message: discord.Message) -> str:
    parts: list[str] = []
    if message.content:
        parts.append(message.content)

    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
        for field in embed.fields:
            if field.name:
                parts.append(field.name)
            if field.value:
                parts.append(field.value)

    return "\n".join(parts)


async def resolve_channel() -> discord.abc.Messageable | None:
    channel = client.get_channel(CHANNEL_ID)
    if channel is not None:
        return channel

    try:
        return await client.fetch_channel(CHANNEL_ID)
    except Exception as exc:
        logger.error("Unable to access notification channel %s: %s", CHANNEL_ID, exc)
        return None


async def process_total(channel: discord.abc.Messageable, current: int, source_label: str) -> None:
    async with state_lock:
        last = load_last_total()

        if last is None:
            save_last_total(current)
            logger.info("Initial state saved: %s (source=%s)", current, source_label)
            return

        if current <= last:
            logger.info("No changes: current=%s, last=%s (source=%s)", current, last, source_label)
            return

        new_ids = list(range(last + 1, current + 1))
        if len(new_ids) == 1:
            body = f"New kingdom released: **#{new_ids[0]}**"
        else:
            ids = ", ".join(f"**#{value}**" for value in new_ids)
            body = f"New kingdoms released: {ids}"

        prefix = "@everyone " if MENTION_EVERYONE else ""
        message = f"{prefix}[NEW] {body}\nSource: {source_label}"
        allowed_mentions = discord.AllowedMentions(everyone=MENTION_EVERYONE)

        await channel.send(message, allowed_mentions=allowed_mentions)
        save_last_total(current)
        logger.info("Notification sent: %s", body)


@tasks.loop(minutes=CHECK_EVERY_MIN)
async def check_loop() -> None:
    channel = await resolve_channel()
    if channel is None:
        logger.error("Notification channel is unavailable.")
        return

    async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
        try:
            current, source_urls = await fetch_total_kingdoms(session)
        except Exception as exc:
            logger.error("Web check failed: %s", exc)
            return

    source_label = ", ".join(source_urls)
    try:
        await process_total(channel, current, source_label)
    except Exception as exc:
        logger.error("Failed to process web result: %s", exc)


@client.event
async def on_message(message: discord.Message) -> None:
    if not WATCH_CHANNEL_IDS:
        return
    if message.author.bot:
        return
    if message.channel.id not in WATCH_CHANNEL_IDS:
        return

    text = message_to_text(message)
    candidates = extract_candidates(text)
    if not candidates:
        return

    current = max(candidates)
    channel = await resolve_channel()
    if channel is None:
        return

    guild_id = message.guild.id if message.guild else "dm"
    source_label = f"discord://{guild_id}/{message.channel.id}"

    try:
        await process_total(channel, current, source_label)
    except Exception as exc:
        logger.error("Failed to process Discord watcher event: %s", exc)


@client.event
async def on_ready() -> None:
    logger.info("Logged in as %s", client.user)
    logger.info("Polling interval: %s minute(s), sources=%s", CHECK_EVERY_MIN, len(CHECK_URLS))

    if MIN_SOURCE_AGREEMENT > len(CHECK_URLS):
        logger.warning(
            "MIN_SOURCE_AGREEMENT=%s is greater than number of sources=%s. Fallback mode will be used.",
            MIN_SOURCE_AGREEMENT,
            len(CHECK_URLS),
        )

    if WATCH_CHANNEL_IDS:
        logger.info("Discord watcher enabled for channels: %s", ", ".join(str(x) for x in sorted(WATCH_CHANNEL_IDS)))

    if not check_loop.is_running():
        check_loop.start()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set")
    if CHANNEL_ID <= 0:
        raise SystemExit("CHANNEL_ID is not set or invalid")
    if MIN_KINGDOM_ID > MAX_KINGDOM_ID:
        raise SystemExit("MIN_KINGDOM_ID cannot be greater than MAX_KINGDOM_ID")

    client.run(TOKEN)
