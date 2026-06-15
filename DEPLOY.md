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

   | Key             | Value                                            |
   |-----------------|--------------------------------------------------|
   | `BOT_TOKEN`     | `8231594493:AAGE8-...` (BotFather bergan token)  |
   | `ADMIN_CHAT_ID` | `1193213437`                                     |

6. **Create / Deploy** bosing. 2–3 daqiqada bot ishga tushadi.
   Loglarda `Bot ishga tushdi` va `Health-check server ...` ko'rinsa — tayyor ✅

Render sizga `https://super-uzbek-bot.onrender.com` kabi manzil beradi.
Brauzerda ochsangiz `✅ Bot ishlayapti` chiqadi.

---

## 3-bosqich. Uxlab qolmasligi uchun (MUHIM!)

Render bepul tarifi 15 daqiqa harakatsizlikdan keyin botni **uxlatadi**.

Buni hal qilish uchun loyihada **GitHub Actions** keep-alive workflow'i bor
(`.github/workflows/keep-alive.yml`). U har 10 daqiqada bot manziliga avtomatik
ping yuboradi — qo'shimcha xizmat (UptimeRobot va h.k.) **kerak emas**.

Workflow GitHub'ga push qilingach o'zi ishlay boshlaydi. Tekshirish:
**GitHub repo → Actions → "Keep Render bot awake"** → "Run workflow" bilan
qo'lda ham sinab ko'rish mumkin.

> ℹ️ Eslatma: repozitoriy 60 kun butunlay harakatsiz qolsa, GitHub jadvalli
> workflow'larni vaqtincha o'chiradi. Faol loyihada muammo bo'lmaydi.

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
