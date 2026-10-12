# 🚀 Botni Render.com'ga bepul yuklash (24/7 ishlashi uchun)

Loyiha tayyor: `render.yaml`, health-check server va `.gitignore` qo'shilgan.
Quyidagi 3 bosqichni ketma-ket bajaring.

---

## 1-bosqich. Kodni GitHub'ga yuklash

1. [github.com/new](https://github.com/new) — yangi repozitoriy yarating
   (masalan nomi: `super-uzbek-bot`, **Private** tanlang).
   `README`, `.gitignore`, `license` qo'shmang — bo'sh qoldiring.

2. GitHub bergan havolani olib, terminalda quyidagini yozing
   (`SIZNING-USERNAME` ni o'zingiznikiga almashtiring):

   ```bash
   git remote add origin https://github.com/SIZNING-USERNAME/super-uzbek-bot.git
   git branch -M main
   git push -u origin main
   ```

   > ⚠️ `.env` fayli GitHub'ga yuklanmaydi (`.gitignore` da bor) — token xavfsiz.

---

## 2-bosqich. Render.com'da servis yaratish

1. [render.com](https://render.com) ga GitHub akkaunti bilan kiring (karta shart emas).
2. **New + → Blueprint** ni tanlang.
3. GitHub repozitoriyangizni ulang — Render `render.yaml` ni o'zi topadi.
4. **Apply** bosing.
5. So'ralganda **Environment Variables** (muhit o'zgaruvchilari) ni kiriting:

   | Key             | Value                                       |
   |-----------------|---------------------------------------------|
   | `BOT_TOKEN`     | BotFather bergan token                       |
   | `ADMIN_CHAT_ID` | Telegram chat ID raqamingiz                  |

6. **Create / Deploy** bosing. 2–3 daqiqada bot ishga tushadi.
Loglarda `Bot ishga tushdi va background tasklar boshlandi` ko'rinsa,
Telegram handlerlari va avtomatik yuborish vazifasi ishga tushgan.

Render sizga `https://super-uzbek-bot.onrender.com` kabi manzil beradi.
Asosiy `/` yo'li Telegram webhook serverida HTTP 404 qaytaradi. Bu servis
HTTP so'roviga javob berganini bildiradi, avtomatik xabar yuborilganini emas.

---

## Bot qanday ishlaydi — WEBHOOK rejimi

Bot **webhook** rejimida ishlaydi: Telegram har bir xabarni to'g'ridan-to'g'ri
Render manziliga yuboradi. Render bepul servisi 15 daqiqa harakatsizlikdan keyin
uxlasa ham, **kelgan xabarning o'zi uni uyg'otadi** — tashqi ping (UptimeRobot,
keep-alive) qo'lda so'ralgan xabarlar uchun shart emas.

- Render `RENDER_EXTERNAL_URL` muhit o'zgaruvchisini avtomatik beradi → bot
  webhook'ni o'zi o'rnatadi (`bot.py` ichida).
- Lokal kompyuterda (`RENDER_EXTERNAL_URL` yo'q) bot **polling** rejimida ishlaydi.

> ℹ️ Yagona kamchilik: uzoq jimlikdan keyin **birinchi** xabarga javob ~30–50s
> kechikadi (servis uyg'onayotgani uchun). Keyingi xabarlar tez ishlaydi.

`.github/workflows/keep-alive.yml` workflow'i ixtiyoriy — u vaqti-vaqti bilan
ping yuborib servisni uyg'oq tutadi. Avtomatik kundalik xabarlar belgilangan
vaqtga yaqin yuborilishi uchun bu workflow yoqilgan bo'lishi kerak.

Workflow Super Uzbek bot va Avtoelon servislarini alohida tekshiradi.
GitHub `schedule` ishga tushishni kechiktirishi mumkin; uni aniq soatdagi
yuborishga kafolat deb hisoblamang. Server kech uyg'onsa, saqlanib qolgan
sozlamalardagi shu kunning yuborilmagan xabarlari jo'natiladi. Manba yoki
Telegram vaqtincha ishlamasa, qayta urinishlar orasida 5 daqiqa kutiladi.
Bugun o'tib ketgan vaqt yangi tanlansa, jadval ertasi kundan boshlanadi.

## Avtomatik xabar sozlamalarini saqlash

Bot foydalanuvchi tanlagan vaqtlarni `notification_settings.json` faylida
saqlaydi. Lokal kompyuterda bu fayl qayta ishga tushirishdan keyin ham qoladi.

Render Free servisida lokal fayllar doimiy emas: servis uxlaganda, qayta ishga
tushganda yoki deploy qilinganda sozlamalar yo'qoladi. Free tarifga doimiy
disk ulab bo'lmaydi. Doimiy Render disk ulangan pullik servis bo'lsa,
quyidagi environment variable'ni disk ichidagi manzilga sozlang:

```text
NOTIFICATION_SETTINGS_FILE=/var/data/notification_settings.json
```

Doimiy saqlashsiz avtomatik xabarlarni ishonchli deb bo'lmaydi. Free servisda
barqaror ishlatish uchun tashqi doimiy baza va tashqi uyg'otish jadvali kerak.
Rasmiy cheklovlar: https://render.com/docs/free

## Bepul doimiy saqlash va aniqroq uyg'otish

1. Supabase Free'da bot uchun alohida loyiha yarating (https://supabase.com/pricing).
2. Connect -> Session pooler manzilini oling. Render Environment'da
   `NOTIFICATION_DATABASE_URL` qilib saqlang; parolni chat yoki GitHub'ga yozmang.
   Sertifikat xususiy CA bilan imzolangan bo'lsa, Supabase Database Settings'dan
   CA sertifikatini olib Render Secret Files'ga qo'shing va
   `NOTIFICATION_DATABASE_CA_FILE=/etc/secrets/supabase-ca.crt` ni sozlang.
   Standart ommaviy CA'lar uchun mavjud certifi to'plami ishlatiladi.
3. Bot ishga tushganda `bot_private.notification_settings` jadvali yaratiladi.
   Bu xususiy schema Supabase'ning public REST API'siga chiqarilmaydi.
4. Supabase SQL Editor'da `supabase_notification_wake.sql` ni bajaring.
   Jadval har daqiqada tekshiriladi; xabar vaqtidan 3 daqiqa oldin va
   yuborilmagan xabar bo'lgandagina Render uyg'otiladi. GitHub schedule'ning
   kechikishiga bog'liqlik kamayadi, servis bekoriga sutka bo'yi uyg'oq qolmaydi.
5. Botda vaqtlarni bir marta qayta tanlang. Keyingi uyqu, restart va deploylarda
   sozlamalar bazada qoladi. Baza ulanishi xato bo'lsa, bot lokal faylga yashirin
   qaytmaydi: ishga tushish xato bilan to'xtaydi yoki saqlashda xatolik beradi.

Ulanishda TLS sertifikati tekshiriladi. Yuborilgan sana va qayta urinish uchun
5 daqiqalik band qilish ham bazada saqlanadi. Telegram muvaffaqiyatli qabul
qilgan zahoti server o'chib qolsa va sana yozilmasa, kamdan-kam takroriy xabar
ehtimoli qoladi; Telegram sendMessage idempotent kalit qabul qilmaydi.

Supabase Free faol bo'lmagan loyihani 1 haftadan keyin pauza qilishi mumkin,
Render Free esa oylik bepul soatlarni boshqa servislar bilan bo'lishadi.
Ikkala bepul tarif ham uzluksiz xizmat yoki aynan sekunddagi yuborishni kafolatlamaydi.

---

## Kodni yangilaganda

O'zgartirish kiritsangiz, qayta yuklash uchun:

```bash
git add .
git commit -m "yangilanish"
git push
```

Render avtomatik ravishda yangi versiyani deploy qiladi.

---

## Eslatma — xavfsizlik

Token chatda va eski `.env` da ko'ringan. Agar bot ommaviy bo'lsa,
[@BotFather](https://t.me/BotFather) → `/revoke` orqali tokenni yangilab,
Render'dagi `BOT_TOKEN` ni ham yangilang.
