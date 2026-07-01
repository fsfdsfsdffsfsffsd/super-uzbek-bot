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
SYNC_TOKEN=uzun_tasodifiy_maxfiy_matn
NEW_LINK=https://t.me/AvtoMashinaBozorElonlar
ALLOW_PUBLIC_SYNC=false
CATCHUP_LIMIT=50
DEST_SCAN_LIMIT=1500
CATCHUP_INTERVAL_SECONDS=300
```

Start command:

```text
python userbot.py
```

Render/Heroku-style serverlar uchun `Procfile` ham qo'shilgan:

```text
worker: python userbot.py
```

## Uxlab qolgan postlarni tutib olish

`userbot.py` ishga tushganda manba kanalning oxirgi `CATCHUP_LIMIT` ta xabarini tekshiradi va yuborilmaganlarini yuboradi. Keyin har `CATCHUP_INTERVAL_SECONDS` sekundda yana tekshiradi.

Destination kanalga yuborilgan postlarga ko'rinmaydigan marker qo'shiladi. Shu marker orqali bot restart/deploydan keyin ham qaysi source post qaysi destination postga ketganini tiklaydi va reply xabarlarni o'sha destination postga reply qilib yuboradi.

Qo'lda sync qilish uchun `SYNC_TOKEN` kerak:

```text
https://SERVER-URL.onrender.com/sync?token=SYNC_TOKEN_QIYMATI
```

Statusni ko'rish uchun ham token kerak:

```text
https://SERVER-URL.onrender.com/status?token=SYNC_TOKEN_QIYMATI
```

GitHub Actions orqali keep-alive sync ishlashi uchun GitHub repo sozlamalarida
`AVTOELON_SYNC_TOKEN` nomli secret oching va Render'dagi `SYNC_TOKEN` bilan bir
xil qiymat kiriting. Tokenni kodga yozmang.

## Muhim

- Sizning user akkauntingiz manba kanalni ko'ra olishi kerak.
- Destination kanalga post qilish uchun akkauntingiz admin yoki post yozish huquqiga ega bo'lishi kerak.
- `userbot_session.session` faylini hech kimga bermang. U akkauntingiz session kaliti hisoblanadi.
