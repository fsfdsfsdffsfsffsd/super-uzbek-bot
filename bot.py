import logging
import os
import re
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- SOZLAMALAR ---
# Tokenni kodga yozmang! Terminalda quyidagicha o'rnating:
#   Linux/Mac:  export BOT_TOKEN="yangi_tokeningiz"
#   Windows:    set BOT_TOKEN=yangi_tokeningiz
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DEST_CHANNEL = os.environ.get("DEST_CHANNEL", "@AvtoMashinaBozorElonlar")

NEW_LINK = os.environ.get("NEW_LINK", "https://t.me/AvtoMashinaBozorElonlar")

HISTORY_FILE = os.environ.get("HISTORY_FILE", "sent_posts_history.txt")

# Barcha taklif (invite) havolalarini ushlaydigan pattern.
# Ushlaydigan ko'rinishlar:
#   https://t.me/joinchat/XXXX
#   https://telegram.me/joinchat/XXXX
#   https://t.me/+XXXX   (yangi format)
#   tg://join?invite=XXXX
# Katta-kichik harf farqi yo'q (IGNORECASE), "https://"siz ham ishlaydi.
INVITE_RE = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)[\w-]+'
    r'|tg://join\?invite=[\w-]+',
    re.IGNORECASE
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def replace_links(text: str) -> str:
    """Matndagi har qanday taklif havolasini NEW_LINK ga almashtiradi."""
    if not text:
        return text
    return INVITE_RE.sub(NEW_LINK, text)


# --- XOTIRANI YUKLASH ---
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f.readlines())


# --- XOTIRAGA YOZISH ---
def save_to_history(unique_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{unique_id}\n")


SENT_POSTS = load_history()


async def post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return

    try:
        unique_id = None

        # --- 1. DUBLIKATNI ANIQLASH ---
        if hasattr(msg, 'forward_origin') and msg.forward_origin:
            origin = msg.forward_origin
            if getattr(origin, 'type', None) == 'channel':
                unique_id = f"{origin.chat.id}_{origin.message_id}"
                if unique_id in SENT_POSTS:
                    await msg.reply_text("[OLDIN] Bu post oldin yuborilgan! (Bot xotirasida bor)")
                    return

        # --- 2. HAVOLANI O'ZGARTIRISH ---
        original_caption = msg.caption or msg.text or ""
        new_caption = replace_links(original_caption)

        # --- 3. KANALGA YUBORISH (qayta urinish bilan) ---
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if msg.text:
                    await context.bot.send_message(
                        chat_id=DEST_CHANNEL,
                        text=new_caption,
                        parse_mode=None,
                    )
                else:
                    await context.bot.copy_message(
                        chat_id=DEST_CHANNEL,
                        from_chat_id=msg.chat_id,
                        message_id=msg.message_id,
                        caption=new_caption if new_caption else None,
                        parse_mode=None,
                    )
                break  # Muvaffaqiyatli bo'lsa chiqamiz
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(
                        f"Urinish {attempt + 1} muvaffaqiyatsiz: {e}. Qayta urinilmoqda..."
                    )
                    await asyncio.sleep(5)
                else:
                    raise  # 3 marta ham ishlamasa xatolikni yuqoriga uzatamiz

        # --- 4. MUVAFFAQIYATLI BO'LSA, SAQLASH ---
        if unique_id:
            SENT_POSTS.add(unique_id)
            save_to_history(unique_id)

        await msg.reply_text("[OK] Yuborildi!")

    except Exception as e:
        logging.error(f"XATOLIK: {e}")
        try:
            await msg.reply_text(f"[XATO] Xatolik bo'ldi: {e}")
        except Exception:
            pass


if __name__ == '__main__':
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN topilmadi! Avval muhit o'zgaruvchisini o'rnating:\n"
            '  export BOT_TOKEN="yangi_tokeningiz"'
        )

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    handler = MessageHandler(filters.ALL & (~filters.COMMAND), post_handler)
    application.add_handler(handler)

    logging.info(f"Bot ishga tushdi! Xotirada {len(SENT_POSTS)} ta post bor.")
    application.run_polling()
