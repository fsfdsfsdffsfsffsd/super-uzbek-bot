import asyncio
import base64
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
CONFIG_ERRORS: list[str] = []


def read_int_env(name: str, default: int, min_value: Optional[int] = None) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        CONFIG_ERRORS.append(
            f"{name} butun son bo'lishi kerak: {raw_value!r}; {default} ishlatiladi"
        )
        return default
    if min_value is not None:
        return max(min_value, value)
    return value


SESSION_NAME = os.environ.get("SESSION_NAME", "userbot_session")
TELETHON_SESSION = os.environ.get("TELETHON_SESSION")
NEW_LINK = os.environ.get("NEW_LINK", "https://t.me/AvtoMashinaBozorElonlar")

HISTORY_FILE = os.environ.get("HISTORY_FILE", "sent_posts_history.txt")
STATE_FILE = os.environ.get("STATE_FILE", "post_state.json")
CATCHUP_LIMIT = read_int_env("CATCHUP_LIMIT", 500, min_value=1)
DEST_SCAN_LIMIT = read_int_env("DEST_SCAN_LIMIT", 1500, min_value=1)
CATCHUP_INTERVAL_SECONDS = read_int_env("CATCHUP_INTERVAL_SECONDS", 300, min_value=1)
START_FROM_SOURCE_ID = read_int_env("START_FROM_SOURCE_ID", 0, min_value=0)
SYNC_TOKEN = os.environ.get("SYNC_TOKEN")
ALLOW_PUBLIC_SYNC = os.environ.get("ALLOW_PUBLIC_SYNC", "false").lower() in {
    "1",
    "true",
    "yes",
}
SKIP_REPLIES = os.environ.get("SKIP_REPLIES", "true").lower() not in {
    "0",
    "false",
    "no",
}

# Telegram caption limit is 1024; text message limit is 4096.
MAX_CAPTION_LENGTH = 1024
MAX_TEXT_LENGTH = 4096

# Barcha taklif (invite) havolalarini ushlaydigan pattern.
INVITE_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)[\w-]+"
    r"|tg://join\?invite=[\w-]+",
    re.IGNORECASE,
)

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
LAST_SOURCE_ID = 0
PROCESS_LOCK = asyncio.Lock()
SYNC_LOCK = asyncio.Lock()
BOT_READY = False
STARTUP_ERROR: Optional[str] = None


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


def parse_state_data(data: dict) -> tuple[set[str], dict[str, int], int]:
    sent = {str(item) for item in data.get("sent", [])}
    post_map = {
        str(source_id): int(dest_id)
        for source_id, dest_id in data.get("post_map", {}).items()
    }
    last_source_id = int(data.get("last_source_id", 0))
    return sent, post_map, last_source_id


def load_state() -> tuple[set[str], dict[str, int], int]:
    if not os.path.exists(STATE_FILE):
        return set(), {}, 0
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return parse_state_data(data)
    except Exception as error:
        logger.warning("State fayl o'qilmadi, yangidan boshlanadi: %s", error)
        return set(), {}, 0


STATE_SENT, POST_MAP, LAST_SOURCE_ID = load_state()
SENT_POSTS = load_history() | STATE_SENT | set(POST_MAP)


def build_state_data() -> dict:
    return {
        "sent": sorted(SENT_POSTS),
        "post_map": POST_MAP,
        "last_source_id": LAST_SOURCE_ID,
    }


def save_state() -> None:
    data = build_state_data()
    tmp_file = f"{STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_file, STATE_FILE)


def build_unique_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}_{message_id}"


def extract_source_id(unique_id: str, chat_id: int) -> Optional[int]:
    prefix = f"{chat_id}_"
    if not unique_id.startswith(prefix):
        return None
    try:
        return int(unique_id[len(prefix) :])
    except ValueError:
        return None


def max_known_source_id(chat_id: int) -> int:
    max_id = 0
    for unique_id in SENT_POSTS | set(POST_MAP):
        source_id = extract_source_id(unique_id, chat_id)
        if source_id is not None:
            max_id = max(max_id, source_id)
    return max_id


def set_last_source_id(source_id: int, reason: str) -> bool:
    global LAST_SOURCE_ID

    source_id = int(source_id)
    if source_id == LAST_SOURCE_ID:
        return False
    old_source_id = LAST_SOURCE_ID
    LAST_SOURCE_ID = source_id
    logger.info(
        "last_source_id belgilandi: %s -> %s (%s)",
        old_source_id,
        LAST_SOURCE_ID,
        reason,
    )
    return True


def advance_last_source_id(source_id: int, reason: str) -> bool:
    if source_id <= LAST_SOURCE_ID:
        return False
    return set_last_source_id(source_id, reason)


def restore_last_source_id_from_known_state(chat_id: int) -> None:
    if START_FROM_SOURCE_ID > 0:
        if set_last_source_id(START_FROM_SOURCE_ID, "START_FROM_SOURCE_ID env override"):
            save_state()
        return

    if advance_last_source_id(max_known_source_id(chat_id), "history/state"):
        save_state()


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


def is_reply_message(message) -> bool:
    return get_reply_source_id(message) is not None


def get_reply_dest_id(chat_id: int, messages: list) -> Optional[int]:
    for message in messages:
        reply_source_id = get_reply_source_id(message)
        if reply_source_id:
            return POST_MAP.get(build_unique_id(chat_id, reply_source_id))
    return None


def remember_source_only(chat_id: int, source_ids: list[int]) -> None:
    new_unique_ids: list[str] = []
    for source_id in source_ids:
        unique_id = build_unique_id(chat_id, source_id)
        if unique_id not in SENT_POSTS:
            new_unique_ids.append(unique_id)
        SENT_POSTS.add(unique_id)

    remember_source_seen(chat_id, source_ids)
    if new_unique_ids:
        save_many_to_history(new_unique_ids)
    save_state()


def remember_mapping(chat_id: int, source_ids: list[int], dest_messages: list) -> None:
    if not source_ids:
        return
    if not dest_messages:
        remember_source_only(chat_id, source_ids)
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

    remember_source_seen(chat_id, source_ids)
    if new_unique_ids:
        save_many_to_history(new_unique_ids)
    save_state()


def remember_source_seen(chat_id: int, source_ids: list[int]) -> None:
    global LAST_SOURCE_ID

    if SOURCE_CHAT_ID is not None and chat_id != SOURCE_CHAT_ID:
        return
    if source_ids:
        LAST_SOURCE_ID = max(LAST_SOURCE_ID, max(int(source_id) for source_id in source_ids))


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
            remember_source_seen(chat_id, source_ids)
            save_state()
            logger.info("Dublikat o'tkazib yuborildi: %s", unique_id)
            return False

        if SKIP_REPLIES and is_reply_message(message):
            SENT_POSTS.add(unique_id)
            remember_source_seen(chat_id, source_ids)
            save_to_history(unique_id)
            save_state()
            logger.info("Reply post o'tkazib yuborildi: %s", unique_id)
            return False

        text = replace_links(message.message or "")
        if not text and not has_file_media(message):
            SENT_POSTS.add(unique_id)
            remember_source_seen(chat_id, source_ids)
            save_to_history(unique_id)
            save_state()
            logger.info("Bo'sh/service xabar o'tkazib yuborildi: %s", unique_id)
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
        logger.info("Yangi post yuborildi: %s", unique_id)
        return True


async def process_album_messages(client, chat_id: int, messages: list, from_catchup: bool = False) -> bool:
    messages = sorted(messages, key=lambda item: item.id)
    source_ids = [int(message.id) for message in messages]
    unique_ids = [build_unique_id(chat_id, message_id) for message_id in source_ids]

    async with PROCESS_LOCK:
        if any(unique_id in SENT_POSTS for unique_id in unique_ids):
            remember_source_only(chat_id, source_ids)
            logger.info("Album to'liq yoki qisman dublikat, o'tkazib yuborildi: %s", unique_ids[0])
            return False

        if SKIP_REPLIES and any(is_reply_message(message) for message in messages):
            SENT_POSTS.update(unique_ids)
            remember_source_seen(chat_id, source_ids)
            save_many_to_history(unique_ids)
            save_state()
            logger.info("Reply album o'tkazib yuborildi: %s", unique_ids[0])
            return False

        caption_source = next((message.message for message in messages if message.message), "")
        caption = replace_links(caption_source)
        files = [message.media for message in messages if has_file_media(message)]
        if not files and not caption:
            SENT_POSTS.update(unique_ids)
            remember_source_seen(chat_id, source_ids)
            save_many_to_history(unique_ids)
            save_state()
            logger.info("Bo'sh album o'tkazib yuborildi: %s", unique_ids[0])
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
            remember_source_seen(chat_id, source_ids)

    if new_ids:
        save_many_to_history(new_ids)
    save_state()
    logger.info(
        "Destination scan tugadi: %s ta xabar, %s ta marker, xotirada %s ta post, last_source_id=%s.",
        scanned,
        markers_found,
        len(SENT_POSTS),
        LAST_SOURCE_ID,
    )


async def set_unknown_state_baseline(client, source_ref) -> None:
    async for message in client.iter_messages(source_ref, limit=1):
        if advance_last_source_id(int(message.id), "unknown state baseline"):
            save_state()
        logger.warning(
            "Ishonchli state topilmadi. Eski postlar qayta yuborilmasligi uchun "
            "baseline source_id=%s qilib olindi. Agar o'tkazib yuborilgan postlarni "
            "tiklash kerak bo'lsa START_FROM_SOURCE_ID env'ni oxirgi yuborilgan "
            "source IDga qo'ying.",
            LAST_SOURCE_ID,
        )
        return

    logger.warning("Manba kanalda post topilmadi, catch-up o'tkazib yuborildi.")


async def catch_up_recent(client, source_ref) -> int:
    async with SYNC_LOCK:
        source_messages_by_id = {}
        start_id = LAST_SOURCE_ID

        if start_id <= 0:
            await set_unknown_state_baseline(client, source_ref)
            return 0

        async for message in client.iter_messages(source_ref, min_id=start_id, reverse=True):
            if int(message.id) > start_id:
                source_messages_by_id[int(message.id)] = message

        # Fallback faqat start_id'dan keyingi xabarlarni tekshiradi. Oldingi
        # versiyada bu joy eski bo'shliqlarni "yangi" deb yuborib yuborishi mumkin edi.
        async for message in client.iter_messages(source_ref, limit=CATCHUP_LIMIT):
            message_id = int(message.id)
            if message_id <= start_id:
                break
            source_messages_by_id.setdefault(message_id, message)

        source_messages = list(source_messages_by_id.values())

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

        logger.info(
            "Catch-up tugadi: start_id=%s, tekshirildi=%s, yangi yuborildi=%s, last_source_id=%s.",
            start_id,
            len(source_messages),
            sent_count,
            LAST_SOURCE_ID,
        )
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
    if BOT_READY:
        return web.Response(text="Avtoelon userbot ishlayapti\n")

    details = STARTUP_ERROR or "Telegram qismi hali tayyor emas"
    return web.Response(text=f"Avtoelon userbot web server ishlayapti, lekin bot tayyor emas: {details}\n")


def is_authorized(request: web.Request) -> bool:
    token = request.query.get("token") or request.headers.get("X-Sync-Token")
    if SYNC_TOKEN:
        return token == SYNC_TOKEN
    return ALLOW_PUBLIC_SYNC


async def status_check(request: web.Request) -> web.Response:
    if not is_authorized(request):
        return web.Response(status=403, text="Forbidden")

    payload = {
        "ok": BOT_READY,
        "telegram_ready": BOT_READY,
        "sent": len(SENT_POSTS),
        "mapped": len(POST_MAP),
        "last_source_id": LAST_SOURCE_ID,
    }
    if STARTUP_ERROR:
        payload["startup_error"] = STARTUP_ERROR
    if CONFIG_ERRORS:
        payload["config_warnings"] = CONFIG_ERRORS
    return web.json_response(payload, status=200 if BOT_READY else 503)


async def sync_check(request: web.Request) -> web.Response:
    if not is_authorized(request):
        return web.Response(status=403, text="Forbidden")

    if STARTUP_ERROR:
        return web.Response(status=503, text=f"Userbot tayyor emas: {STARTUP_ERROR}\n")

    sync_callback = request.app.get("sync_callback")
    if not sync_callback:
        return web.Response(status=503, text="Sync hali tayyor emas")

    sent_count = await sync_callback()
    return web.Response(text=f"Sync tugadi. Yangi yuborilgan: {sent_count}\n")


async def start_health_server(sync_callback=None):
    port = os.environ.get("PORT")
    if not port:
        return None

    app = web.Application()
    app["sync_callback"] = sync_callback
    app.router.add_get("/", health_check)
    app.router.add_get("/status", status_check)
    app.router.add_get("/sync", sync_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(port))
    await site.start()
    logger.info("Health-check server 0.0.0.0:%s portda ishga tushdi.", port)
    return runner


async def start_telegram_client(client: TelegramClient) -> None:
    logger.info("Telegram client ulanmoqda...")
    if TELETHON_SESSION:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                "TELETHON_SESSION yaroqsiz yoki eskirgan. Lokal kompyuterda "
                "export_session.py bilan yangi session yarating va Render env'ni yangilang."
            )
    else:
        await client.start()
    logger.info("Telegram client ulandi va session tasdiqlandi.")


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
        raise RuntimeError(
            "Quyidagi env qiymatlar topilmadi: "
            + ", ".join(missing)
            + "\nMasalan PowerShell:\n"
            + '  $env:API_ID="123456"\n'
            + '  $env:API_HASH="abcdef123456..."\n'
            + '  $env:SOURCE_CHANNEL="@ManbaKanal"\n'
            + '  $env:DEST_CHANNEL="@AvtoMashinaBozorElonlar"\n'
            + "  python userbot.py"
        )

    try:
        api_id = int(API_ID)
    except ValueError as error:
        raise RuntimeError(f"API_ID butun son bo'lishi kerak: {API_ID!r}") from error

    return api_id, API_HASH, SOURCE_CHANNEL, DEST_CHANNEL


async def main() -> None:
    global BOT_READY, DEST_CHANNEL, SOURCE_CHAT_ID, STARTUP_ERROR

    health_runner = await start_health_server()
    periodic_task = None
    client = None

    try:
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

        await start_telegram_client(client)
        logger.info("Source kanal entity olinmoqda: %s", source_channel)
        source_entity = await client.get_entity(source_ref)
        SOURCE_CHAT_ID = get_peer_id(source_entity)
        logger.info("Source kanal topildi: %s -> %s", source_channel, SOURCE_CHAT_ID)
        restore_last_source_id_from_known_state(SOURCE_CHAT_ID)

        logger.info("Destination marker scan boshlanmoqda: limit=%s", DEST_SCAN_LIMIT)
        await rebuild_state_from_destination(client)

        async def sync_callback() -> int:
            return await catch_up_recent(client, source_ref)

        if health_runner:
            health_runner.app["sync_callback"] = sync_callback
        periodic_task = asyncio.create_task(periodic_catch_up(sync_callback))

        logger.info("Startup catch-up boshlanmoqda...")
        await sync_callback()
        BOT_READY = True
        STARTUP_ERROR = None
        logger.info(
            "Userbot ishga tushdi. Manba: %s (%s), kanal: %s, xotirada: %s ta post, last_source_id=%s.",
            source_channel,
            SOURCE_CHAT_ID,
            DEST_CHANNEL,
            len(SENT_POSTS),
            LAST_SOURCE_ID,
        )
        await client.run_until_disconnected()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        BOT_READY = False
        STARTUP_ERROR = str(error)
        logger.exception("Userbot ishga tushmadi: %s", error)
        if client:
            await client.disconnect()
        if health_runner:
            await asyncio.Event().wait()
        raise
    finally:
        if periodic_task:
            periodic_task.cancel()
        if health_runner:
            await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
