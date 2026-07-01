import asyncio
import logging
import os
import re
from typing import Iterable, Optional

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession


# --- SOZLAMALAR ---
# Kerakli env qiymatlar:
#   API_ID          my.telegram.org dan olinadi
#   API_HASH        my.telegram.org dan olinadi
#   SOURCE_CHANNEL  post olinadigan kanal username yoki id
#   DEST_CHANNEL    post yuboriladigan kanal username yoki id
#
# Misol:
#   $env:API_ID="123456"
#   $env:API_HASH="abcdef123456..."
#   $env:SOURCE_CHANNEL="@ManbaKanal"
#   $env:DEST_CHANNEL="@AvtoMashinaBozorElonlar"
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")
DEST_CHANNEL = os.environ.get("DEST_CHANNEL", "@AvtoMashinaBozorElonlar")

SESSION_NAME = os.environ.get("SESSION_NAME", "userbot_session")
TELETHON_SESSION = os.environ.get("TELETHON_SESSION")
NEW_LINK = os.environ.get("NEW_LINK", "https://t.me/AvtoMashinaBozorElonlar")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "sent_posts_history.txt")

# Barcha taklif (invite) havolalarini ushlaydigan pattern.
INVITE_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)[\w-]+"
    r"|tg://join\?invite=[\w-]+",
    re.IGNORECASE,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def replace_links(text: Optional[str]) -> Optional[str]:
    """Matndagi har qanday taklif havolasini NEW_LINK ga almashtiradi."""
    if not text:
        return text
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


SENT_POSTS = load_history()


def build_unique_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}_{message_id}"


def parse_chat_ref(value: str):
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value


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


async def handle_single_post(event: events.NewMessage.Event) -> None:
    message = event.message
    unique_id = build_unique_id(event.chat_id, message.id)

    if unique_id in SENT_POSTS:
        logger.info("Dublikat o'tkazib yuborildi: %s", unique_id)
        return

    text = replace_links(message.message or "")

    if message.media:
        await send_with_retry(
            event.client.send_file,
            DEST_CHANNEL,
            message.media,
            caption=text or None,
            parse_mode="html",
        )
    else:
        await send_with_retry(
            event.client.send_message,
            DEST_CHANNEL,
            text or "",
            parse_mode="html",
            link_preview=False,
        )

    SENT_POSTS.add(unique_id)
    save_to_history(unique_id)
    logger.info("Yangi post yuborildi: %s", unique_id)


async def handle_album(event: events.Album.Event) -> None:
    messages = list(event.messages)
    unique_ids = [build_unique_id(event.chat_id, message.id) for message in messages]

    if all(unique_id in SENT_POSTS for unique_id in unique_ids):
        logger.info("Album dublikati o'tkazib yuborildi: %s", unique_ids[0])
        return

    caption_source = next((message.message for message in messages if message.message), "")
    caption = replace_links(caption_source)
    files = [message.media for message in messages if message.media]

    if files:
        await send_with_retry(
            event.client.send_file,
            DEST_CHANNEL,
            files,
            caption=caption or None,
            parse_mode="html",
        )
    elif caption:
        await send_with_retry(
            event.client.send_message,
            DEST_CHANNEL,
            caption,
            parse_mode="html",
            link_preview=False,
        )

    SENT_POSTS.update(unique_ids)
    save_many_to_history(unique_ids)
    logger.info("Yangi album yuborildi: %s ta xabar", len(unique_ids))


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
    global DEST_CHANNEL

    api_id, api_hash, source_channel, dest_channel = require_env()

    source_ref = parse_chat_ref(source_channel)
    DEST_CHANNEL = parse_chat_ref(dest_channel)
    session = StringSession(TELETHON_SESSION) if TELETHON_SESSION else SESSION_NAME
    client = TelegramClient(session, api_id, api_hash)

    @client.on(events.Album(chats=source_ref))
    async def album_listener(event: events.Album.Event) -> None:
        try:
            await handle_album(event)
        except Exception as error:
            logger.exception("Album yuborishda xatolik: %s", error)

    @client.on(events.NewMessage(chats=source_ref))
    async def message_listener(event: events.NewMessage.Event) -> None:
        if event.message.grouped_id:
            return
        try:
            await handle_single_post(event)
        except Exception as error:
            logger.exception("Post yuborishda xatolik: %s", error)

    await client.start()
    logger.info(
        "Userbot ishga tushdi. Manba: %s, kanal: %s, xotirada: %s ta post.",
        source_channel,
        DEST_CHANNEL,
        len(SENT_POSTS),
    )
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
