import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from typing import Iterable, Optional

from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage
from telethon.utils import get_peer_id


# --- SOZLAMALAR ---
# Kerakli env qiymatlar:
#   API_ID          my.telegram.org dan olinadi
#   API_HASH        my.telegram.org dan olinadi
#   SOURCE_CHANNEL  post olinadigan kanal username yoki id
#   DEST_CHANNEL    post yuboriladigan kanal username yoki id
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")
DEST_CHANNEL = os.environ.get("DEST_CHANNEL", "@AvtoMashinaBozorElonlar")

SESSION_NAME = os.environ.get("SESSION_NAME", "userbot_session")
TELETHON_SESSION = os.environ.get("TELETHON_SESSION")
NEW_LINK = os.environ.get("NEW_LINK", "https://t.me/AvtoMashinaBozorElonlar")

HISTORY_FILE = os.environ.get("HISTORY_FILE", "sent_posts_history.txt")
STATE_FILE = os.environ.get("STATE_FILE", "post_state.json")
CATCHUP_LIMIT = int(os.environ.get("CATCHUP_LIMIT", "50"))
DEST_SCAN_LIMIT = int(os.environ.get("DEST_SCAN_LIMIT", "1500"))
CATCHUP_INTERVAL_SECONDS = int(os.environ.get("CATCHUP_INTERVAL_SECONDS", "300"))
SYNC_TOKEN = os.environ.get("SYNC_TOKEN")

# Telegram caption limit is 1024; text message limit is 4096.
MAX_CAPTION_LENGTH = 1024
MAX_TEXT_LENGTH = 4096

# Barcha taklif (invite) havolalarini ushlaydigan pattern.
INVITE_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)[\w-]+"
    r"|tg://join\?invite=[\w-]+",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")

# Invisible state marker. Destination posts keep this marker, so the bot can
# rebuild duplicate history and reply mapping after Render sleep/restart.
ZERO = "\u200b"
ONE = "\u200c"
MARKER_START = "\u2063\u2063"
MARKER_END = "\u2064\u2064"
MARKER_RE = re.compile(
    re.escape(MARKER_START)
    + f"([{re.escape(ZERO)}{re.escape(ONE)}]+)"
    + re.escape(MARKER_END)
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SOURCE_CHAT_ID: Optional[int] = None
POST_MAP: dict[str, int] = {}
DEST_TEXT_FINGERPRINTS: set[str] = set()
PROCESS_LOCK = asyncio.Lock()
SYNC_LOCK = asyncio.Lock()


def replace_links(text: Optional[str]) -> str:
    """Matndagi har qanday taklif havolasini NEW_LINK ga almashtiradi."""
    if not text:
        return ""
    return INVITE_RE.sub(NEW_LINK, text)


def load_history() -> set[str]:
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as file:
        return {line.strip() for line in file if line.strip()}


def save_to_history(unique_id: str) -> None:
    with open(HISTORY_FILE, "a", encoding="utf-8") as file:
        file.write(f"{unique_id}\n")


def save_many_to_history(unique_ids: Iterable[str]) -> None:
    with open(HISTORY_FILE, "a", encoding="utf-8") as file:
        for unique_id in unique_ids:
            file.write(f"{unique_id}\n")


def load_state() -> tuple[set[str], dict[str, int]]:
    if not os.path.exists(STATE_FILE):
        return set(), {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        sent = {str(item) for item in data.get("sent", [])}
        post_map = {
            str(source_id): int(dest_id)
            for source_id, dest_id in data.get("post_map", {}).items()
        }
        return sent, post_map
    except Exception as error:
        logger.warning("State fayl o'qilmadi, yangidan boshlanadi: %s", error)
        return set(), {}


STATE_SENT, POST_MAP = load_state()
SENT_POSTS = load_history() | STATE_SENT | set(POST_MAP)


def save_state() -> None:
    data = {
        "sent": sorted(SENT_POSTS),
        "post_map": POST_MAP,
    }
    tmp_file = f"{STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_file, STATE_FILE)


def build_unique_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}_{message_id}"


def has_file_media(message) -> bool:
    return bool(message.media) and not isinstance(message.media, MessageMediaWebPage)


def parse_chat_ref(value: str):
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def compact_ids(message_ids: list[int]) -> str:
    if not message_ids:
        return ""
    sorted_ids = sorted(message_ids)
    if sorted_ids == list(range(sorted_ids[0], sorted_ids[-1] + 1)):
        return f"{sorted_ids[0]}-{sorted_ids[-1]}"
    return ",".join(str(message_id) for message_id in sorted_ids)


def expand_ids(value: str) -> list[int]:
    if not value:
        return []
    if "," not in value and "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part) for part in value.split(",") if part]


def encode_marker(chat_id: int, message_ids: list[int]) -> str:
    payload = f"{chat_id}|{compact_ids(message_ids)}".encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    bits = "".join(format(byte, "08b") for byte in encoded.encode("ascii"))
    return MARKER_START + "".join(ONE if bit == "1" else ZERO for bit in bits) + MARKER_END


def decode_markers(text: str) -> list[tuple[int, list[int]]]:
    decoded: list[tuple[int, list[int]]] = []
    for match in MARKER_RE.finditer(text or ""):
        bits = match.group(1)
        if len(bits) % 8:
            continue
        encoded = "".join(
            chr(int(bits[index : index + 8].replace(ZERO, "0").replace(ONE, "1"), 2))
            for index in range(0, len(bits), 8)
        )
        encoded += "=" * (-len(encoded) % 4)
        try:
            payload = base64.urlsafe_b64decode(encoded).decode("utf-8")
            chat_id, ids_value = payload.split("|", 1)
            decoded.append((int(chat_id), expand_ids(ids_value)))
        except Exception:
            logger.debug("Marker o'qilmadi", exc_info=True)
    return decoded


def strip_markers(text: Optional[str]) -> str:
    return MARKER_RE.sub("", text or "").strip()


def attach_marker(text: str, marker: str, max_length: int) -> str:
    visible_text = strip_markers(text)
    separator = "\n" if visible_text else ""
    allowed_visible_length = max_length - len(marker) - len(separator)
    if allowed_visible_length < 0:
        return marker[:max_length]
    if len(visible_text) > allowed_visible_length:
        visible_text = visible_text[:allowed_visible_length].rstrip()
    return f"{visible_text}{separator}{marker}" if visible_text else marker


def text_fingerprint(text: Optional[str]) -> Optional[str]:
    visible_text = replace_links(strip_markers(text))
    visible_text = WHITESPACE_RE.sub(" ", visible_text).strip()
    if not visible_text:
        return None
    return hashlib.sha256(visible_text.encode("utf-8")).hexdigest()


def normalize_sent_messages(result) -> list:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def get_reply_source_id(message) -> Optional[int]:
    reply_to = getattr(message, "reply_to", None)
    if not reply_to:
        return None
    return getattr(reply_to, "reply_to_msg_id", None)


def get_reply_dest_id(chat_id: int, messages: list) -> Optional[int]:
    for message in messages:
        reply_source_id = get_reply_source_id(message)
        if reply_source_id:
            return POST_MAP.get(build_unique_id(chat_id, reply_source_id))
    return None


def remember_mapping(chat_id: int, source_ids: list[int], dest_messages: list) -> None:
    if not source_ids or not dest_messages:
        return

    new_unique_ids: list[str] = []
    first_dest_id = int(dest_messages[0].id)
    for index, source_id in enumerate(source_ids):
        unique_id = build_unique_id(chat_id, source_id)
        dest_message = dest_messages[index] if index < len(dest_messages) else dest_messages[0]
        dest_id = int(getattr(dest_message, "id", first_dest_id))
        if unique_id not in SENT_POSTS:
            new_unique_ids.append(unique_id)
        SENT_POSTS.add(unique_id)
        POST_MAP[unique_id] = dest_id

    if new_unique_ids:
        save_many_to_history(new_unique_ids)
    save_state()


async def send_with_retry(send_func, *args, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await send_func(*args, **kwargs)
        except FloodWaitError as error:
            wait_seconds = int(error.seconds) + 1
            logger.warning("FloodWait: %s soniya kutilmoqda...", wait_seconds)
            await asyncio.sleep(wait_seconds)
        except Exception as error:
            if attempt < max_retries - 1:
                logger.warning(
                    "Urinish %s muvaffaqiyatsiz: %s. Qayta urinilmoqda...",
                    attempt + 1,
                    error,
                )
                await asyncio.sleep(5)
            else:
                raise


async def process_single_message(client, chat_id: int, message, from_catchup: bool = False) -> bool:
    unique_id = build_unique_id(chat_id, message.id)
    source_ids = [int(message.id)]

    async with PROCESS_LOCK:
        if unique_id in SENT_POSTS:
            logger.info("Dublikat o'tkazib yuborildi: %s", unique_id)
            return False

        text = replace_links(message.message or "")
        if not text and not has_file_media(message):
            SENT_POSTS.add(unique_id)
            save_to_history(unique_id)
            save_state()
            logger.info("Bo'sh/service xabar o'tkazib yuborildi: %s", unique_id)
            return False

        fingerprint = text_fingerprint(text)
        if from_catchup and fingerprint and fingerprint in DEST_TEXT_FINGERPRINTS:
            SENT_POSTS.add(unique_id)
            save_to_history(unique_id)
            save_state()
            logger.info("Oldin yuborilgan post fingerprint orqali tanildi: %s", unique_id)
            return False

        marker = encode_marker(chat_id, source_ids)
        reply_to = get_reply_dest_id(chat_id, [message])

        if has_file_media(message):
            caption = attach_marker(text, marker, MAX_CAPTION_LENGTH)
            result = await send_with_retry(
                client.send_file,
                DEST_CHANNEL,
                message.media,
                caption=caption,
                parse_mode=None,
                reply_to=reply_to,
            )
        else:
            outgoing_text = attach_marker(text, marker, MAX_TEXT_LENGTH)
            result = await send_with_retry(
                client.send_message,
                DEST_CHANNEL,
                outgoing_text,
                parse_mode=None,
                link_preview=True,
                reply_to=reply_to,
            )

        dest_messages = normalize_sent_messages(result)
        remember_mapping(chat_id, source_ids, dest_messages)
        if fingerprint:
            DEST_TEXT_FINGERPRINTS.add(fingerprint)
        logger.info("Yangi post yuborildi: %s", unique_id)
        return True


async def process_album_messages(client, chat_id: int, messages: list, from_catchup: bool = False) -> bool:
    messages = sorted(messages, key=lambda item: item.id)
    source_ids = [int(message.id) for message in messages]
    unique_ids = [build_unique_id(chat_id, message_id) for message_id in source_ids]

    async with PROCESS_LOCK:
        if all(unique_id in SENT_POSTS for unique_id in unique_ids):
            logger.info("Album dublikati o'tkazib yuborildi: %s", unique_ids[0])
            return False

        caption_source = next((message.message for message in messages if message.message), "")
        caption = replace_links(caption_source)
        files = [message.media for message in messages if has_file_media(message)]
        if not files and not caption:
            SENT_POSTS.update(unique_ids)
            save_many_to_history(unique_ids)
            save_state()
            logger.info("Bo'sh album o'tkazib yuborildi: %s", unique_ids[0])
            return False

        fingerprint = text_fingerprint(caption)
        if from_catchup and fingerprint and fingerprint in DEST_TEXT_FINGERPRINTS:
            SENT_POSTS.update(unique_ids)
            save_many_to_history(unique_ids)
            save_state()
            logger.info("Oldin yuborilgan album fingerprint orqali tanildi: %s", unique_ids[0])
            return False

        marker = encode_marker(chat_id, source_ids)
        reply_to = get_reply_dest_id(chat_id, messages)

        if files:
            marked_caption = attach_marker(caption, marker, MAX_CAPTION_LENGTH)
            result = await send_with_retry(
                client.send_file,
                DEST_CHANNEL,
                files,
                caption=marked_caption,
                parse_mode=None,
                reply_to=reply_to,
            )
        else:
            outgoing_text = attach_marker(caption, marker, MAX_TEXT_LENGTH)
            result = await send_with_retry(
                client.send_message,
                DEST_CHANNEL,
                outgoing_text,
                parse_mode=None,
                link_preview=True,
                reply_to=reply_to,
            )

        dest_messages = normalize_sent_messages(result)
        remember_mapping(chat_id, source_ids, dest_messages)
        if fingerprint:
            DEST_TEXT_FINGERPRINTS.add(fingerprint)
        logger.info("Yangi album yuborildi: %s ta xabar", len(source_ids))
        return True


async def rebuild_state_from_destination(client) -> None:
    if SOURCE_CHAT_ID is None:
        return

    scanned = 0
    markers_found = 0
    new_ids: list[str] = []

    async for message in client.iter_messages(DEST_CHANNEL, limit=DEST_SCAN_LIMIT):
        scanned += 1
        message_text = message.message or ""
        fingerprint = text_fingerprint(message_text)
        if fingerprint:
            DEST_TEXT_FINGERPRINTS.add(fingerprint)

        for chat_id, source_ids in decode_markers(message_text):
            if chat_id != SOURCE_CHAT_ID:
                continue
            markers_found += 1
            for source_id in source_ids:
                unique_id = build_unique_id(chat_id, source_id)
                if unique_id not in SENT_POSTS:
                    new_ids.append(unique_id)
                SENT_POSTS.add(unique_id)
                POST_MAP.setdefault(unique_id, int(message.id))

    if new_ids:
        save_many_to_history(new_ids)
    save_state()
    logger.info(
        "Destination scan tugadi: %s ta xabar, %s ta marker, xotirada %s ta post.",
        scanned,
        markers_found,
        len(SENT_POSTS),
    )


async def catch_up_recent(client, source_ref) -> int:
    async with SYNC_LOCK:
        source_messages = []
        async for message in client.iter_messages(source_ref, limit=CATCHUP_LIMIT):
            source_messages.append(message)

        sent_count = 0
        processed_groups = set()
        for message in sorted(source_messages, key=lambda item: item.id):
            if getattr(message, "grouped_id", None):
                grouped_id = message.grouped_id
                if grouped_id in processed_groups:
                    continue
                processed_groups.add(grouped_id)
                album_messages = [
                    item for item in source_messages if getattr(item, "grouped_id", None) == grouped_id
                ]
                if await process_album_messages(client, SOURCE_CHAT_ID, album_messages, from_catchup=True):
                    sent_count += 1
                continue

            if await process_single_message(client, SOURCE_CHAT_ID, message, from_catchup=True):
                sent_count += 1

        logger.info("Catch-up tugadi: %s ta yangi post/album yuborildi.", sent_count)
        return sent_count


async def periodic_catch_up(sync_callback) -> None:
    interval = max(60, CATCHUP_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_callback()
        except Exception as error:
            logger.exception("Periodic catch-up xatoligi: %s", error)


async def health_check(request: web.Request) -> web.Response:
    return web.Response(
        text=(
            "Avtoelon userbot ishlayapti\n"
            f"sent={len(SENT_POSTS)}\n"
            f"mapped={len(POST_MAP)}\n"
        )
    )


async def sync_check(request: web.Request) -> web.Response:
    if SYNC_TOKEN and request.query.get("token") != SYNC_TOKEN:
        return web.Response(status=403, text="Forbidden")

    sync_callback = request.app.get("sync_callback")
    if not sync_callback:
        return web.Response(status=503, text="Sync hali tayyor emas")

    sent_count = await sync_callback()
    return web.Response(text=f"Sync tugadi. Yangi yuborilgan: {sent_count}\n")


async def start_health_server(sync_callback):
    port = os.environ.get("PORT")
    if not port:
        return None

    app = web.Application()
    app["sync_callback"] = sync_callback
    app.router.add_get("/", health_check)
    app.router.add_get("/sync", sync_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(port))
    await site.start()
    logger.info("Health-check server 0.0.0.0:%s portda ishga tushdi.", port)
    return runner


def require_env() -> tuple[int, str, str, str]:
    missing = [
        name
        for name, value in {
            "API_ID": API_ID,
            "API_HASH": API_HASH,
            "SOURCE_CHANNEL": SOURCE_CHANNEL,
            "DEST_CHANNEL": DEST_CHANNEL,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(
            "Quyidagi env qiymatlar topilmadi: "
            + ", ".join(missing)
            + "\nMasalan PowerShell:\n"
            + '  $env:API_ID="123456"\n'
            + '  $env:API_HASH="abcdef123456..."\n'
            + '  $env:SOURCE_CHANNEL="@ManbaKanal"\n'
            + '  $env:DEST_CHANNEL="@AvtoMashinaBozorElonlar"\n'
            + "  python userbot.py"
        )

    return int(API_ID), API_HASH, SOURCE_CHANNEL, DEST_CHANNEL


async def main() -> None:
    global DEST_CHANNEL, SOURCE_CHAT_ID

    api_id, api_hash, source_channel, dest_channel = require_env()

    source_ref = parse_chat_ref(source_channel)
    DEST_CHANNEL = parse_chat_ref(dest_channel)
    session = StringSession(TELETHON_SESSION) if TELETHON_SESSION else SESSION_NAME
    client = TelegramClient(session, api_id, api_hash)

    @client.on(events.Album(chats=source_ref))
    async def album_listener(event: events.Album.Event) -> None:
        try:
            await process_album_messages(event.client, event.chat_id, list(event.messages))
        except Exception as error:
            logger.exception("Album yuborishda xatolik: %s", error)

    @client.on(events.NewMessage(chats=source_ref))
    async def message_listener(event: events.NewMessage.Event) -> None:
        if event.message.grouped_id:
            return
        try:
            await process_single_message(event.client, event.chat_id, event.message)
        except Exception as error:
            logger.exception("Post yuborishda xatolik: %s", error)

    await client.start()
    source_entity = await client.get_entity(source_ref)
    SOURCE_CHAT_ID = get_peer_id(source_entity)

    await rebuild_state_from_destination(client)

    async def sync_callback() -> int:
        return await catch_up_recent(client, source_ref)

    health_runner = await start_health_server(sync_callback)
    periodic_task = asyncio.create_task(periodic_catch_up(sync_callback))

    await sync_callback()
    logger.info(
        "Userbot ishga tushdi. Manba: %s (%s), kanal: %s, xotirada: %s ta post.",
        source_channel,
        SOURCE_CHAT_ID,
        DEST_CHANNEL,
        len(SENT_POSTS),
    )

    try:
        await client.run_until_disconnected()
    finally:
        periodic_task.cancel()
        if health_runner:
            await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
