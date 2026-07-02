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
CATCHUP_LIMIT=500
SKIP_REPLIES=true
DEST_SCAN_LIMIT=1500
CATCHUP_INTERVAL_SECONDS=300
START_FROM_SOURCE_ID=0
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

Bu bepul variantda bot faqat aniq state bilan ishlaydi: local `post_state.json`, `sent_posts_history.txt` va destination kanalga qo'shilgan ko'rinmas markerlar. Render free restart/redeploy paytida local fayllar yo'qolsa, bot destination marker scan orqali oxirgi source ID ni tiklaydi.

Marker ham topilmasa, bot source kanalning hozirgi oxirgi postini baseline qiladi va eski postlarni yubormaydi. Bu shubhali backlogni tashlab yuborishi mumkin, lekin 7 kun oldingi noto'g'ri postni yuborishdan xavfsizroq.

`userbot.py` ishga tushganda avval history/state fayllaridan, keyin destination kanal markerlaridan oxirgi source message ID (`last_source_id`) ni tiklaydi. Keyin manba kanalda faqat shu ID'dan keyin chiqqan xabarlarni tartib bilan tekshiradi va yuborilmaganlarini yuboradi.

`CATCHUP_LIMIT=500` oxirgi yangi xabarlarni qo'shimcha tekshirish uchun ishlatiladi, lekin bot `last_source_id`dan eski postlarni hech qachon yubormaydi. Matn o'xshashligi yoki fingerprint orqali "taxminiy oxirgi post" tanlanmaydi.

Agar eski marker/state yo'qolgan bo'lsa yoki bot noto'g'ri yuqori ID saqlab qo'ygan bo'lsa, serverda `START_FROM_SOURCE_ID` qiymatini oxirgi to'g'ri yuborilgan source message ID qilib qo'ying. Bu qiymat qo'lda berilgan override hisoblanadi va history/state'dagi `last_source_id`dan ustun turadi. Masalan oxirgi to'g'ri yuborilgan source post ID `96995` bo'lsa:

```text
START_FROM_SOURCE_ID=96995
```

`SKIP_REPLIES=true` bo'lsa, manba kanalda boshqa postga reply qilib yozilgan xabarlar destination kanalga yuborilmaydi.

Destination kanalga yuborilgan postlarga ko'rinmaydigan marker qo'shiladi. Shu marker orqali bot restart/deploydan keyin ham qaysi source post qaysi destination postga ketganini tiklaydi va reply xabarlarni o'sha destination postga reply qilib yuboradi.

Qo'lda sync qilish uchun `SYNC_TOKEN` kerak:

```text
https://SERVER-URL.onrender.com/sync?token=SYNC_TOKEN_QIYMATI
```

Statusni ko'rish uchun ham token kerak:

```text
https://SERVER-URL.onrender.com/status?token=SYNC_TOKEN_QIYMATI
```

GitHub Actions orqali keep-alive sync ishlashi uchun `.github/workflows/keepalive-sync.yml` qo'shilgan. GitHub repo sozlamalarida ikkita secret oching:

```text
AVTOELON_SYNC_URL=https://SERVER-URL.onrender.com
AVTOELON_SYNC_TOKEN=Render'dagi SYNC_TOKEN bilan bir xil qiymat
```

Workflow har 5 daqiqada `/sync` endpointni chaqiradi. Bu Render free web servisini uxlab qolsa ham uyg'otadi va o'tkazib yuborilgan postlarni `last_source_id`dan keyin catch-up qiladi. Tokenni kodga yozmang.

## Muhim

- Sizning user akkauntingiz manba kanalni ko'ra olishi kerak.
- Destination kanalga post qilish uchun akkauntingiz admin yoki post yozish huquqiga ega bo'lishi kerak.
- `userbot_session.session` faylini hech kimga bermang. U akkauntingiz session kaliti hisoblanadi.
