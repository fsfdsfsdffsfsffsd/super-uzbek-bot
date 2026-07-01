# Userbot ishga tushirish

Bu variant Telegram bot token bilan emas, sizning Telegram user akkauntingiz orqali manba kanalni kuzatadi. Manba kanalga yangi post tushsa, post ichidagi invite linklarni kerakli linkka almashtirib destination kanalga yuboradi.

## 1. Kutubxonalarni o'rnatish

```powershell
pip install -r requirements.txt
```

## 2. Telegram API_ID va API_HASH olish

1. https://my.telegram.org saytiga kiring.
2. Telegram raqamingiz bilan login qiling.
3. `API development tools` bo'limidan `api_id` va `api_hash` oling.

## 3. PowerShell'da sozlamalarni kiriting

```powershell
$env:API_ID="123456"
$env:API_HASH="api_hash_bu_yerga"
$env:SOURCE_CHANNEL="@ManbaKanal"
$env:DEST_CHANNEL="@AvtoMashinaBozorElonlar"
python userbot.py
```

Birinchi ishga tushirishda Telegram telefon raqamingizni, kelgan kodni va agar yoqilgan bo'lsa 2FA parolni so'raydi. Keyin `userbot_session.session` fayli yaratiladi va keyingi safar qayta kod so'ramaydi.

## Serverga qo'yish

Ko'p bepul serverlarda terminal interaktiv Telegram kod so'rashi uchun qulay emas. Shuning uchun avval lokal kompyuterda session string yarating:

```powershell
$env:API_ID="123456"
$env:API_HASH="api_hash_bu_yerga"
py export_session.py
```

Chiqqan uzun `TELETHON_SESSION` qiymatini serverdagi environment/secret sozlamasiga qo'ying. GitHub'ga session fayl yoki session string qo'ymang.

Server env qiymatlari:

```text
API_ID=123456
API_HASH=api_hash_bu_yerga
SOURCE_CHANNEL=@ManbaKanal
DEST_CHANNEL=@AvtoMashinaBozorElonlar
TELETHON_SESSION=export_session.py chiqargan uzun qiymat
NEW_LINK=https://t.me/AvtoMashinaBozorElonlar
```

Start command:

```text
python userbot.py
```

Render/Heroku-style serverlar uchun `Procfile` ham qo'shilgan:

```text
worker: python userbot.py
```

## Muhim

- Sizning user akkauntingiz manba kanalni ko'ra olishi kerak.
- Destination kanalga post qilish uchun akkauntingiz admin yoki post yozish huquqiga ega bo'lishi kerak.
- `userbot_session.session` faylini hech kimga bermang. U akkauntingiz session kaliti hisoblanadi.
