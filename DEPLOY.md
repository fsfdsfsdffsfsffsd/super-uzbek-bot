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
   Loglarda `Bot ishga tushdi` va `Health-check server ...` ko'rinsa — tayyor ✅

Render sizga `https://super-uzbek-bot.onrender.com` kabi manzil beradi.
Brauzerda ochsangiz `✅ Bot ishlayapti` chiqadi.

---

## Bot qanday ishlaydi — WEBHOOK rejimi

Bot **webhook** rejimida ishlaydi: Telegram har bir xabarni to'g'ridan-to'g'ri
Render manziliga yuboradi. Render bepul servisi 15 daqiqa harakatsizlikdan keyin
uxlasa ham, **kelgan xabarning o'zi uni uyg'otadi** — tashqi ping (UptimeRobot,
keep-alive) shart emas.

- Render `RENDER_EXTERNAL_URL` muhit o'zgaruvchisini avtomatik beradi → bot
  webhook'ni o'zi o'rnatadi (`bot.py` ichida).
- Lokal kompyuterda (`RENDER_EXTERNAL_URL` yo'q) bot **polling** rejimida ishlaydi.

> ℹ️ Yagona kamchilik: uzoq jimlikdan keyin **birinchi** xabarga javob ~30–50s
> kechikadi (servis uyg'onayotgani uchun). Keyingi xabarlar tez ishlaydi.

`.github/workflows/keep-alive.yml` workflow'i ixtiyoriy — u vaqti-vaqti bilan
ping yuborib sovuq startlarni kamaytiradi, lekin bot uchun shart emas.

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
