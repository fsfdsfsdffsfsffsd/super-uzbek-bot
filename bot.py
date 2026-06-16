import logging
import asyncio
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
import re
import ssl
import certifi
import os
import sys
# QO'SHILDI: .env faylni o'qish uchun
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from typing import List, Dict, Optional, Any
import time
from dataclasses import dataclass
from enum import Enum

# Windows konsolida emoji (✅, 🕌 ...) chiqarishda UnicodeEncodeError bo'lmasligi uchun
# stdout/stderr ni UTF-8 ga o'tkazamiz
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# .env faylni yuklaymiz
load_dotenv()

# Xavfsiz o'zgaruvchilar
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Token borligini tekshirish (muhim!)
if not BOT_TOKEN:
    logging.critical("XATOLIK: .env faylida BOT_TOKEN topilmadi!")
    sys.exit("Bot tokeni topilmadi. .env faylni tekshiring.")

# Agar ADMIN_CHAT_ID raqam bo'lsa, int() ga o'tkazamiz
if ADMIN_CHAT_ID:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("super_uzbek_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Cache tizimi (OPTIMALLASHTIRILDI: 1000 foydalanuvchi uchun)
cache = {}
CACHE_TIME = 3600  # 1 soat (5 daqiqa o'rniga)

# Rate limiting
last_request_time = {}
RATE_LIMIT_SECONDS = 1  # Tezkor javob uchun biroz kamaytirildi

# Sozlamalar
SETTINGS = {
    "default_city": "Toshkent",
    "language": "uz",
    "notifications": True,
    "cache_time": 3600  # 1 soat
}

class PrayerTime(Enum):
    BOMDOD = "Bomdod"
    QUYOSH = "Quyosh"
    PESHIN = "Peshin"
    ASR = "Asr"
    SHOM = "Shom"
    XUFTON = "Xufton"

@dataclass
class AirQualityData:
    aqi: str
    quality: str
    pollutant: str
    concentration: str
    timestamp: str

@dataclass
class PrayerData:
    times: Dict[PrayerTime, str]
    date: str
    hijri_date: str

@dataclass
class CurrencyData:
    banks: List[Dict[str, Any]]
    timestamp: str

@dataclass
class WeatherData:
    day: str
    periods: Dict[str, Dict[str, str]]
    additional: Dict[str, str]
    timestamp: str

@dataclass
class MagneticData:
    date: str
    hourly_data: List[Dict[str, str]] 
    timestamp: str

class SuperUzbekBot:
    """Barcha funksiyalarni o'z ichiga olgan asosiy bot klassi"""

    def __init__(self):
        self.iqair_url = "https://www.iqair.com/ru/uzbekistan/toshkent-shahri/tashkent"
        self.muslim_url = "https://www.muslim.uz/oz"
        self.bank_url = "https://bank.uz/uz/currency"
        self.weather_url = "https://yandex.uz/pogoda/ru/tashkent?lat=41.330278&lon=69.337088"
        self.forecast_url = "https://yandex.uz/pogoda/ru/tashkent?lat=41.311151&lon=69.279737"
        self.magnetic_url = "https://www.gismeteo.ru/weather-tashkent-5331/gm/"
        self.cached_currency = None
        self.cached_weather = None
        self.cached_prayer = None
        self.cached_air = None
        self.cached_magnetic = None
        self.cached_weather_3day = None  # 3 kunlik ob-havo uchun
        self.cached_magnetic_3day = None  # 3 kunlik magnit uchun
        # Qachon yangilanganini bilish uchun
        self.last_update_time = "Hali yangilanmadi"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'uz-UZ,uz;q=0.9,en;q=0.8,ru;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        self.session = None
        self.background_task = None  # Fon yangilash vazifasi (toza to'xtatish uchun)

    async def start_background_tasks(self):
        """Ma'lumotlarni har 5 daqiqada yangilash (1000 foydalanuvchi uchun optimallashtirildi)"""
        while True:
            try:
                # 1. Valyuta kursi
                logger.info("⏳ Valyuta yangilanmoqda...")
                currency_data = await self.get_currency_rates()
                if currency_data:
                    self.cached_currency = currency_data
            
                await asyncio.sleep(5) 

                # 2. Ob-havo
                logger.info("⏳ Ob-havo yangilanmoqda...")
                weather_data = await self.fetch_weather_data()
                if weather_data:
                    self.cached_weather = weather_data
                
                await asyncio.sleep(5)
                
                # 3. Havo sifati
                logger.info("⏳ Havo sifati yangilanmoqda...")
                air_data = await self.fetch_air_quality()
                if air_data:
                    self.cached_air = air_data
                
                await asyncio.sleep(5)
                
                # 4. Magnit bo'roni
                logger.info("⏳ Magnit bo'roni yangilanmoqda...")
                magnetic_data = await self.fetch_magnetic_storms()
                if magnetic_data:
                    self.cached_magnetic = magnetic_data
                
                await asyncio.sleep(5)
                
                # 5. 3 kunlik ob-havo
                logger.info("⏳ 3 kunlik ob-havo yangilanmoqda...")
                weather_3day = await self.fetch_3day_forecast()
                if weather_3day:
                    self.cached_weather_3day = weather_3day
                
                await asyncio.sleep(5)
                
                # 6. 3 kunlik magnit bo'roni
                logger.info("⏳ 3 kunlik magnit bo'roni yangilanmoqda...")
                magnetic_3day = await self.fetch_3day_magnetic_forecast()
                if magnetic_3day:
                    self.cached_magnetic_3day = magnetic_3day

                await asyncio.sleep(5)

                # 7. Namoz vaqtlari (OXIRIDA - qayta urinish bilan)
                logger.info("⏳ Namoz vaqtlari yangilanmoqda...")
                prayer_attempt = 0
                max_prayer_attempts = 5
                prayer_data = None
            
                while prayer_attempt < max_prayer_attempts and prayer_data is None:
                    prayer_attempt += 1
                    logger.info(f"Namoz vaqtlari: {prayer_attempt}-urinish...")
                    prayer_data = await self.get_prayer_times()
                    
                    if prayer_data:
                        self.cached_prayer = prayer_data
                        logger.info("Namoz vaqtlari muvaffaqiyatli olindi!")
                    else:
                        if prayer_attempt < max_prayer_attempts:
                            wait_time = 10
                            logger.warning(f"Namoz vaqtlari olinmadi. {wait_time} soniyadan keyin qayta uriniladi...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error("Namoz vaqtlarini olishda 5 urinishdan keyin ham xatolik!")

                # Yangilanish vaqtini yozib qo'yamiz
                self.last_update_time = datetime.now().strftime("%H:%M")
                logger.info("Barcha ma'lumotlar muvaffaqiyatli yangilandi!")

                # 5 daqiqa kutish
                await asyncio.sleep(300)
                    
            except Exception as e:
                logger.error(f"Background task xatosi: {e}")
                await asyncio.sleep(60)

    async def create_session(self):
        """Asinxron session yaratish"""
        if self.session is None or self.session.closed:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context, limit=10)
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout, headers=self.headers)
        
        return self.session

    async def close_session(self):
        """Sessionni yopish"""
        if self.session:
            await self.session.close()
            self.session = None

    async def fetch_with_retry(self, url: str, max_retries: int = 3, delay: int = 2) -> Optional[str]:
        session = await self.create_session()
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, ssl=False) as response:
                    if response.status == 200:
                        return await response.text()
                    elif response.status == 429:
                        wait_time = delay * (attempt + 1)
                        logger.warning(f"Rate limit hit. Waiting {wait_time} s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"HTTP xato: {response.status} - {url}")
                        return None
            except asyncio.TimeoutError:
                logger.error(f"Timeout xatosi - {url}")
            except Exception as e:
                logger.error(f"So'rovda xatolik: {str(e)} - {url}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
        
        return None

    def get_uzbek_month_name(self, month_num: int) -> str:
        months = {
            1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel",
            5: "may", 6: "iyun", 7: "iyul", 8: "avgust", 
            9: "sentabr", 10: "oktabr", 11: "noyabr", 12: "dekabr"
        }
        return months.get(month_num, "")

    def get_formatted_date(self) -> str:
        today = datetime.now()
        month_name = self.get_uzbek_month_name(today.month)
        return f"{today.year}-yil {today.day}-{month_name}"

    def get_hijri_date(self) -> str:
        today = datetime.now()
        return f"{today.day:02d}.{today.month:02d}.{today.year}"

    # ========== HAVO SIFATI ==========

    async def fetch_air_quality(self) -> Optional[AirQualityData]:
        cache_key = 'air_quality'
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            return cached_data
        
        try:
            html = await self.fetch_with_retry(self.iqair_url)
            if not html: return None
                
            soup = BeautifulSoup(html, 'html.parser')
            aqi_value = "N/A"
            quality = "N/A"
            pollutant = "N/A"
            concentration = "N/A"
            
            selectors = [
                ('p', {'class': 'text-lg font-medium'}),
                ('div', {'class': 'aqi-value'}),
                ('span', {'class': 'indexValue'}),
                ('div', {'class': 'indexValue'})
            ]
            
            for tag, attrs in selectors:
                element = soup.find(tag, attrs)
                if element and element.text.strip():
                    aqi_value = re.sub(r'[^\d]', '', element.text.strip())
                    if aqi_value: break
            
            quality_selectors = [('p', {'class': 'font-body-l-medium'}), ('div', {'class': 'level-name'})]
            for tag, attrs in quality_selectors:
                element = soup.find(tag, attrs)
                if element and element.text.strip():
                    quality = element.text.strip()
                    break
            
            result = AirQualityData(
                aqi=aqi_value, quality=quality, pollutant=pollutant,
                concentration=concentration, timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            self._set_cached_data(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Havo sifati xato: {str(e)}")
            return None

    def get_aqi_emoji(self, aqi_value: str) -> str:
        try:
            aqi = int(aqi_value)
            if aqi <= 50: return "🟢"
            elif aqi <= 100: return "🟡"
            elif aqi <= 150: return "🟠"
            elif aqi <= 200: return "🔴"
            elif aqi <= 300: return "🟣"
            else: return "🟤"
        except: return "⚪"

    def get_recommendations(self, aqi_value: str) -> str:
        try:
            aqi = int(aqi_value)
            if aqi <= 50: return "Havo top-toza! Mazza qilib ko'chada aylansangiz bo'ladi." 
            elif aqi <= 100: return "Havo yomon emas, lekin sal chang bor. Allergiyasi borlar ehtiyot bo'lsin."      
            elif aqi <= 150: return "Havo aynib qoldi. Yosh bolalar va qariyalarni ko'p ko'chada olib yurmang." 
            elif aqi <= 200: return "Havo buzildi. Zarur bo'lmasa ko'chaga chiqmang, maska taqing." 
            elif aqi <= 300: return "Ahvol chatoq! Derazalarni mahkam yoping, uydan chiqmang."
            else: return "Vahima! Tashqariga umuman chiqmang. Havo o'ta darajada ifloslangan." 
        except: return "Ma'lumot mavjud emas"

    def format_air_quality_md(self, data: dict) -> str:
        """Havo sifati xabari (3-Variant: Batafsil va Aniq statuslar bilan)"""
        try:
            aqi = int(data['aqi'])
        except:
            aqi = 0
            
        if aqi <= 50:
            emoji, status = "🟢", "Yaxshi"
        elif aqi <= 100:
            emoji, status = "🟡", "O'rtacha"
        elif aqi <= 150:
            emoji, status = "🟠", "Zaif guruhlar uchun zararli"
        elif aqi <= 200:
            emoji, status = "🔴", "Zararli"
        elif aqi <= 300:
            emoji, status = "🟣", "Juda zararli"
        else:
            emoji, status = "🟤", "Xavfli"

        result = (
            f"😷 *Havoning Tozaligi*\n"
            f"📅 {data['date']}\n"
            f"📍 {data['location']} \n\n"
            
            f"📉 AQI Indeksi: *{data['aqi']}*\n"
            f"{emoji} Havo holati: *{status}*\n\n"
            
            f"💡 *Tavsiya:*\n"
            f"{data['advice']}\n\n"
            
            f"_Ma'lumot IQAir.com saytidan olindi_"
        )
        return result

    # ========== NAMOZ VAQTLARI ==========

    async def get_prayer_times(self) -> Optional[PrayerData]:
        cache_key = 'prayer_times'
        cached_data = self._get_cached_data(cache_key)
        if cached_data: return cached_data

        try:
            html = await self.fetch_with_retry(self.muslim_url)
            if not html: return None

            soup = BeautifulSoup(html, 'html.parser')
            prayer_div = soup.find('div', id='prayer')
            
            if not prayer_div:
                header_center = soup.find('div', class_='header-center')
                if header_center: prayer_div = header_center.find('div', id='prayer')

            if not prayer_div: return None

            prayer_times = {}
            time_divs = prayer_div.find_all('div', class_='flex-column')
            if not time_divs:
                all_divs = prayer_div.find_all('div', recursive=True)
                time_divs = [div for div in all_divs if 'border-right' in div.get('class', [])]

            for div in time_divs:
                elems = div.find_all(['div', 'span', 'p'])
                if len(elems) >= 2:
                    p_name = elems[0].get_text(strip=True)
                    p_time = elems[1].get_text(strip=True)
                    
                    name_map = {
                        'Бомдод': PrayerTime.BOMDOD, 'Қуёш': PrayerTime.QUYOSH,
                        'Пешин': PrayerTime.PESHIN, 'Аср': PrayerTime.ASR,
                        'Шом': PrayerTime.SHOM, 'Хуфтон': PrayerTime.XUFTON
                    }
                    for k, v in name_map.items():
                        if k in p_name:
                            prayer_times[v] = p_time
                            break

            if len(prayer_times) >= 5:
                result = PrayerData(
                    times=prayer_times, date=datetime.now().strftime('%d.%m.%Y'),
                    hijri_date=self.get_hijri_date()
                )
                self._set_cached_data(cache_key, result)
                return result
            return None
        except Exception as e:
            logger.error(f"Namoz vaqtlari xato: {str(e)}")
            return None
    
    def format_prayer_times(self, data: PrayerData) -> str:
        if not data: return "❌ Namoz vaqtlarini olishda xatolik yuz berdi"
        formatted_date = self.get_formatted_date()
        result = (
            f"🕌 *Namoz Vaqtlari*\n"
            f"📅 {formatted_date}\n"
            f"📍 {SETTINGS['default_city']} shahri\n\n"
        )
        order = [
            (PrayerTime.BOMDOD, "Bomdod", "🌅"), (PrayerTime.QUYOSH, "Quyosh", "☀️"),
            (PrayerTime.PESHIN, "Peshin", "🌞"), (PrayerTime.ASR, "Asr", "⛅"),
            (PrayerTime.SHOM, "Shom", "🌇"), (PrayerTime.XUFTON, "Xufton", "🌙")
        ]
        for p_enum, p_name, emoji in order:
            time_str = data.times.get(p_enum, "N/A")
            result += f"{emoji} *{p_name}:* {time_str}\n"
        result += "\n_Ma'lumot muslim.uz saytidan olindi_"
        return result

    # ========== VALYUTA KURSLARI ==========

    async def get_currency_rates(self) -> Optional[CurrencyData]:
        cache_key = 'currency_rates'
        cached_data = self._get_cached_data(cache_key)
        if cached_data: return cached_data
        
        try:
            html = await self.fetch_with_retry(self.bank_url)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                banks_data = []
                buy_banks = {}
                sell_banks = {}
                
                buy_section = soup.find('div', class_='bc-inner-blocks-left')
                if buy_section:
                    for item in buy_section.find_all('div', class_='bc-inner-block-left-texts'):
                        lnk = item.find('a')
                        spn = item.find('span', class_='green-date') or item.find('span', class_='rate-value')
                        if lnk and spn:
                            try:
                                val = float(re.sub(r'[^\d.]', '', spn.get_text(strip=True)))
                                buy_banks[lnk.get_text(strip=True)] = val
                            except: continue

                sell_section = soup.find('div', class_='bc-inner-blocks-right')
                if sell_section:
                    for item in sell_section.find_all('div', class_='bc-inner-block-left-texts'):
                        lnk = item.find('a')
                        spn = item.find('span', class_='green-date') or item.find('span', class_='rate-value')
                        if lnk and spn:
                            try:
                                val = float(re.sub(r'[^\d.]', '', spn.get_text(strip=True)))
                                sell_banks[lnk.get_text(strip=True)] = val
                            except: continue
                
                all_banks = set(list(buy_banks.keys()) + list(sell_banks.keys()))
                for b in all_banks:
                    d = {'name': b, 'buy': buy_banks.get(b, 0), 'sell': sell_banks.get(b, 0)}
                    if d['buy'] > 0 or d['sell'] > 0: banks_data.append(d)
                
                result = CurrencyData(banks=banks_data, timestamp=datetime.now().strftime('%d.%m.%Y %H:%M'))
                self._set_cached_data(cache_key, result)
                return result
        except Exception as e:
            logger.error(f"Valyuta xato: {str(e)}")
        return None


    def format_all_banks_md(self, data: CurrencyData) -> str:
        """Barcha banklarni rasmdagi kabi ikki guruhga bo'lib, saralab chiqarish"""
        if not data or not data.banks: 
            return "❌ Ma'lumot mavjud emas."
        
        formatted_date = self.get_formatted_date()
        
        result = (
            f"💵 *Valyutalar Kursi (Barcha banklar)*\n"
            f"📅 {formatted_date}\n"
            f"📍 O'zbekiston banklari\n\n"
        )
        
        sell_list = [b for b in data.banks if b.get('sell', 0) > 0]
        sorted_for_buying = sorted(sell_list, key=lambda x: x['sell'])
        
        result += "✅ *Dollar olish uchun eng yaxshi:*\n"
        for b in sorted_for_buying:
            price = f"{b['sell']:,.0f}".replace(",", " ")
            result += f"🏦 {b['name']} – {price} so'm\n"
            
        result += "\n"
        
        buy_list = [b for b in data.banks if b.get('buy', 0) > 0]
        sorted_for_selling = sorted(buy_list, key=lambda x: x['buy'], reverse=True)
        
        result += "✅ *Dollar maydalash uchun eng yaxshi:*\n"
        for b in sorted_for_selling:
            price = f"{b['buy']:,.0f}".replace(",", " ")
            result += f"🏦 {b['name']} – {price} so'm\n"
            
        result += "\n_Ma'lumot bank.uz saytidan olindi_"
        return result

    def format_currency_rates(self, currency_data: CurrencyData) -> str:
        if not currency_data or not currency_data.banks: return "❌ Valyuta kurslarini olishda xatolik"
        formatted_date = self.get_formatted_date()
        result = (f"💵 *Valyutalar Kursi*\n📅 {formatted_date}\n📍 O'zbekiston banklari\n\n")
        
        valid_sell = [b for b in currency_data.banks if b.get('sell', 0) > 0]
        if valid_sell:
            best_sell = sorted(valid_sell, key=lambda x: x['sell'])[:5]
            result += "✅ *Dollar olish uchun eng yaxshi:*\n"
            for b in best_sell:
                result += f"🏦 {b['name']} – {b['sell']:,.0f} so'm\n".replace(",", " ")
        
        valid_buy = [b for b in currency_data.banks if b.get('buy', 0) > 0]
        if valid_buy:
            best_buy = sorted(valid_buy, key=lambda x: x['buy'], reverse=True)[:5]
            result += "\n✅ *Dollar maydalash uchun eng yaxshi:*\n"
            for b in best_buy:
                result += f"🏦 {b['name']} – {b['buy']:,.0f} so'm\n".replace(",", " ")
        
        result += "\n_Ma'lumot bank.uz saytidan olindi_"
        return result

    # ========== OB-HAVO ==========

    async def fetch_weather_data(self) -> Optional[WeatherData]:
        cache_key = 'weather_data'
        cached_data = self._get_cached_data(cache_key)
        if cached_data: return cached_data
        
        try:
            html = await self.fetch_with_retry(self.weather_url)
            if not html: return None
            soup = BeautifulSoup(html, 'html.parser')
            
            weather_article = soup.find('article', class_=re.compile("AppForecastDay_container")) or \
                              soup.find('div', class_='forecast-briefly__day')
            
            if not weather_article: return None
            
            day_name = "Bugun"
            periods = {}
            p_map = {'m': '🌅 Ertalab', 'd': '☀️ Kunduzi', 'e': '🌆 Kechasi', 'n': '🌙 Tuni'}
            
            for p_code, p_name in p_map.items():
                temp_el = weather_article.find('div', style=re.compile(f"grid-area:{p_code}-temp")) or \
                          weather_article.find('span', class_='temp__value')
                
                temp = temp_el.get_text(strip=True) if temp_el else "N/A"
                
                cond_el = weather_article.find('div', style=re.compile(f"grid-area:{p_code}-text")) or \
                          weather_article.find('div', class_='weather__value')
                
                cond = cond_el.get_text(strip=True) if cond_el else "N/A"
                periods[p_code] = {'name': p_name, 'temp': temp, 'condition': cond}
            
            result = WeatherData(day=day_name, periods=periods, additional={}, timestamp=datetime.now().strftime('%d.%m.%Y %H:%M'))
            self._set_cached_data(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Ob-havo xato: {str(e)}")
            return None

    async def fetch_3day_forecast(self) -> str:
        """3 kunlik ob-havoni parsing qiluvchi yangilangan funksiya"""
        url = self.forecast_url.replace("/ru/", "/uz/")
        
        html_txt = await self.fetch_with_retry(url)
        if not html_txt: return "❌ Ma'lumot olishda xatolik."

        try:
            soup = BeautifulSoup(html_txt, 'html.parser')
            articles = soup.find_all('article', class_=re.compile("AppForecastDay_container"))
            
            if not articles:
                return "❌ Ob-havo ma'lumotlari topilmadi."

            result_text = "📅 *Keyingi 3 kunlik ob-havo:*\n\n"
            
            for article in articles[:3]:
                title_tag = article.find('h3', class_=re.compile("AppForecastDayHeader_dayTitle"))
                raw_title = title_tag.get_text(strip=True) if title_tag else "Sana noma'lum"
                title = self.translate_date_to_uz(raw_title)

                day_temp_tag = article.find('div', style=re.compile("grid-area:d-temp"))
                day_temp = day_temp_tag.get_text(strip=True) if day_temp_tag else "N/A"

                night_temp_tag = article.find('div', style=re.compile("grid-area:n-temp"))
                night_temp = night_temp_tag.get_text(strip=True) if night_temp_tag else "N/A"

                cond_tag = article.find('div', style=re.compile("grid-area:d-text"))
                condition = cond_tag.get_text(strip=True) if cond_tag else ""
                condition = self.translate_weather_condition(condition)

                result_text += (
                    f"🗓 *{title}*\n"
                    f"☀️ Kunduzi: *{day_temp}*\n"
                    f"🌙 Kechasi: *{night_temp}*\n"
                    f"☁️ {condition}\n\n"
                )
            
            result_text += "_Ma'lumot yandex.uz saytidan olindi_"
            return result_text

        except Exception as e:
            logger.error(f"3 kunlik ob-havo parsing xato: {e}")
            return "❌ Parsingda xatolik yuz berdi."


    def translate_date_to_uz(self, date_str: str) -> str:
        """Ruscha sanalarni o'zbekchaga o'girish va chiziqcha (-) qo'yish"""
        d = date_str.lower()
        
        replacements = {
            "сегодня": "Bugun", "завтра": "Ertaga",
            "понедельник": "Dushanba", "вторник": "Seshanba", "среда": "Chorshanba",
            "четверг": "Payshanba", "пятница": "Juma", "суббота": "Shanba", "воскресенье": "Yakshanba",
            "пн": "Dushanba", "вт": "Seshanba", "ср": "Chorshanba", "чт": "Payshanba",
            "пт": "Juma", "сб": "Shanba", "вс": "Yakshanba",
            "января": "yanvar", "февраля": "fevral", "марта": "mart", "апреля": "aprel",
            "мая": "may", "июня": "iyun", "июля": "iyul", "августа": "avgust",
            "сентября": "sentabr", "октября": "oktabr", "ноября": "noyabr", "декабря": "dekabr",
            "янв": "yanvar", "фев": "fevral", "мар": "mart", "апр": "aprel",
            "май": "may", "июн": "iyun", "июл": "iyul", "авг": "avgust",
            "сен": "sentabr", "окт": "oktabr", "ноя": "noyabr", "дек": "dekabr"
        }
        
        for rus, uzb in replacements.items():
            if rus in d:
                d = d.replace(rus, uzb)
        
        months_regex = "yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentabr|oktabr|noyabr|dekabr"
        d = re.sub(rf"(\d+)\s+({months_regex})", r"\1-\2", d)

        return d.title()

    def translate_weather_condition(self, condition: str) -> str:
        translations = {
            "ясно": "Quyoshli", "переменная облачность": "O'zgaruvchan",
            "облачно с прояснениями": "Ochiq bulutli", "пасмурно": "Bulutli",
            "небольшой дождь": "Yengil yomg'ir", "дождь": "Yomg'ir",
            "снег": "Qor", "туман": "Tuman", "clear": "Quyoshli", "cloudy": "Bulutli",
            "дождь со снегом": "Yomg'ir va qor"
        }
        return translations.get(condition.lower(), condition.capitalize())

    def get_weather_emoji(self, condition: str) -> str:
        c = condition.lower()
        if "quyosh" in c or "clear" in c: return "☀️"
        if "bulut" in c or "cloud" in c: return "☁️"
        if "yomg'ir" in c or "rain" in c: return "🌧️"
        if "qor" in c or "snow" in c: return "❄️"
        return "🌤️"

    def format_weather_data_md(self, data: dict) -> str:
        return (
            f"*🌤 Ob-havo Ma'lumotlari*\n"
            f"📅 {data['date']}\n"
            f"📍 {data['location']}\n\n"
            f"*{data['morning_emoji']} Ertalab:* {data['morning_temp']}\n"
            f"*{data['day_emoji']} Kunduzi:* {data['day_temp']}\n"
            f"*{data['evening_emoji']} Kechasi:* {data['evening_temp']}\n"
            f"*{data['night_emoji']} Tunda:* {data['night_temp']}\n\n"
            f"_Ma'lumot yandex.uz saytidan olindi_"
        )

    # ========== MAGNIT BO'RONI ==========

    async def fetch_magnetic_storms(self) -> Optional[MagneticData]:
        cache_key = 'magnetic_data'
        cached_data = self._get_cached_data(cache_key)
        if cached_data: return cached_data

        try:
            html = await self.fetch_with_retry(self.magnetic_url)
            if not html: return None
            soup = BeautifulSoup(html, 'html.parser')
            wrap = soup.find('div', class_='gm-wrap')
            if not wrap: return None

            times = [t.text.strip() for t in wrap.find_all('div', class_='time')]
            values = [v.text.strip() for v in wrap.find_all('div', class_='value')]
            
            hourly_data = []
            if times and values:
                for t, v in zip(times[:8], values[:8]):
                    hourly_data.append({"time": t, "index": v})

            result = MagneticData(date="Bugun", hourly_data=hourly_data, timestamp=datetime.now().strftime('%d.%m.%Y %H:%M'))
            self._set_cached_data(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Magnit xato: {str(e)}")
            return None

    async def fetch_3day_magnetic_forecast(self) -> str:
        """3 kunlik magnit bo'roni prognozi (YANGILANGAN DIZAYN)"""
        try:
            html = await self.fetch_with_retry(self.magnetic_url)
            if not html: return "❌ Ma'lumot olishda xatolik."

            soup = BeautifulSoup(html, 'html.parser')
            
            date_divs = soup.find_all('div', class_=re.compile("date"))
            value_divs = soup.find_all('div', class_=re.compile("value"))

            if not date_divs or not value_divs:
                 return "❌ Ma'lumot topilmadi."

            result_text = "🧲 *Keyingi 3 kunlik holat:*\n\n"
            
            count = 0
            for i in range(len(date_divs)):
                if count >= 3: break
                
                raw_date = date_divs[i].get_text(strip=True)
                clean_date = self.translate_date_to_uz(raw_date) 
                
                try:
                    k_index = value_divs[i].get_text(strip=True)
                    if len(k_index) > 2: k_index = k_index[:1]
                    idx = int(k_index)
                except:
                    k_index = "?"
                    idx = 0

                if idx <= 4: 
                    emoji, status = "🟢", "Tinch holat"
                elif idx == 5:
                    emoji, status = "🟡", "Kuchsiz bo'ron"
                elif idx == 6: 
                    emoji, status = "🟠", "O'rtacha bo'ron" 
                elif idx == 7:
                    emoji, status = "🔴", "Kuchli bo'ron"
                elif idx >= 8: 
                    emoji, status = "🟣", "Juda kuchli bo'ron"
                else: 
                    emoji, status = "⚪", "Noma'lum"

                result_text += (
                    f"📅 *{clean_date}*\n"
                    f"{emoji} {k_index}-ball — {status}\n\n"
                )
                count += 1
            
            return result_text

        except Exception as e:
            logger.error(f"3 kunlik magnit xato: {e}")
            return "❌ Xatolik yuz berdi."

    def format_magnetic_data(self, data: MagneticData) -> str:
        if not data: return "❌ Magnit bo'roni ma'lumotlarini olishda xatolik"
        
        result = (
            f"🧲 *Magnit Bo'ronlari*\n"
            f"📅 {self.get_formatted_date()}\n"
            f"📍 Toshkent shahri\n\n"
        )
        
        for item in data.hourly_data:
            try:
                idx = int(item['index'])
                if idx <= 4: emoji = "🟢"
                elif idx == 5: emoji = "🟡"
                elif idx == 6: emoji = "🟠"
                elif idx == 7: emoji = "🔴"
                elif idx >= 8: emoji = "🟣"
            except: 
                emoji = "⚪"
            
            time_str = item['time']
            if len(time_str) == 4 and time_str[1] == ':':
                time_str = "0" + time_str
                
            result += f"{emoji} {time_str} — {item['index']} ball\n"
            
        result += (
            f"\n*Ballar shkalasi:*\n"
            f"4 ball — Tinch holat\n"
            f"5 ball — Kuchsiz bo'ron\n"
            f"6 ball — O'rtacha bo'ron\n"
            f"7 ball — Kuchli bo'ron\n"
            f"8 ball — Juda kuchli bo'ron\n\n"
            f"_Ma'lumot gismeteo.ru saytidan olindi_"
        )
        return result

    # ========== CACHE ==========

    def _get_cached_data(self, key: str) -> Any:
        if key in cache:
            item = cache[key]
            if time.time() - item['time'] < item.get('expiry', CACHE_TIME):
                return item['data']
        return None

    def _set_cached_data(self, key: str, data: Any, expiry: int = None) -> None:
        cache[key] = {'data': data, 'time': time.time(), 'expiry': expiry or CACHE_TIME}

bot = SuperUzbekBot()

# ========== KLAVIATURA (KEYBOARD) ==========

def get_main_keyboard():
    """Xabar yozish joyida turadigan doimiy tugmalar"""
    keyboard = [
        [KeyboardButton("🕌 Namoz vaqti"), KeyboardButton("💵 Valyuta kursi")],
        [KeyboardButton("🌤 Ob-havo"), KeyboardButton("😷 Havo tozaligi")],
        [KeyboardButton("🧲 Magnit bo'roni")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# ========== HANDLERLAR ==========

async def check_rate_limit(user_id: int) -> bool:
    current = time.time()
    if user_id in last_request_time:
        if current - last_request_time[user_id] < RATE_LIMIT_SECONDS:
            return False
    last_request_time[user_id] = current
    return True

async def send_typing_action(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Yozayotgandek ko'rsatish"""
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Chat action jo'natishda xatolik: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = f"👋 *Salom, {user.first_name}!*\n\nQuyidagi tugmalardan birini tanlang 👇"
    await update.message.reply_text(
        welcome_message, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )

async def inline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Ma'lumot yuklanmoqda...") 
    
    if query.data == "weather_3days":
        if not bot.cached_weather_3day:  # Cache bo'sh bo'lsa — darhol yuklaymiz
            res = await bot.fetch_3day_forecast()
            if res and not res.startswith("❌"):
                bot.cached_weather_3day = res  # Faqat to'g'ri natijani saqlaymiz
            forecast_text = res
        else:
            forecast_text = bot.cached_weather_3day
        await query.message.reply_text(forecast_text, parse_mode=ParseMode.MARKDOWN)

    elif query.data == "magnetic_3days":
        if not bot.cached_magnetic_3day:  # Cache bo'sh bo'lsa — darhol yuklaymiz
            res = await bot.fetch_3day_magnetic_forecast()
            if res and not res.startswith("❌"):
                bot.cached_magnetic_3day = res
            forecast_text = res
        else:
            forecast_text = bot.cached_magnetic_3day
        await query.message.reply_text(forecast_text, parse_mode=ParseMode.MARKDOWN)

    elif query.data == "all_banks":
        if bot.cached_currency:
             text = bot.format_all_banks_md(bot.cached_currency)
             await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
             return

        loading_msg = await query.message.reply_text("⏳ _Barcha banklar ro'yxati yuklanmoqda..._", parse_mode=ParseMode.MARKDOWN)
        
        data = await bot.get_currency_rates()
        if data:
            bot.cached_currency = data
            
        text = bot.format_all_banks_md(data)
        await loading_msg.delete()
        
        try:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.message.reply_text("❌ Xatolik: Ro'yxat juda uzun.")
            logger.error(f"Banklar ro'yxati xato: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha matnli xabarlarni ushlab olib, tegishli funksiyaga yo'naltiradi"""
    text = update.message.text
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not await check_rate_limit(user_id):
        await update.message.reply_text("⏳ Biroz sekinroq...")
        return

    # 1. Namoz
    if "Namoz" in text:
        await send_typing_action(chat_id, context)
        if not bot.cached_prayer:  # Cache bo'sh bo'lsa (sovuq start) — darhol yuklaymiz
            bot.cached_prayer = await bot.get_prayer_times()
        if bot.cached_prayer:
            response = bot.format_prayer_times(bot.cached_prayer)
        else:
            response = "⚠️ Namoz vaqtlarini hozir olishning iloji bo'lmadi (manba vaqtincha ishlamayapti). Birozdan keyin qayta urinib ko'ring."
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard())

    # 2. Valyuta
    elif "Valyuta" in text:
        await send_typing_action(chat_id, context)
        if not bot.cached_currency:
            bot.cached_currency = await bot.get_currency_rates()
        if bot.cached_currency:
            response = bot.format_currency_rates(bot.cached_currency)
        else:
            response = "⚠️ Valyuta kurslarini hozir olishning iloji bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        currency_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦 Barcha banklarni ko'rish", callback_data="all_banks")]
        ])
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN, reply_markup=currency_kb)
    
    # 3. Ob-havo
    elif "Ob-havo" in text:
        await send_typing_action(chat_id, context)
        if not bot.cached_weather:  # Cache bo'sh bo'lsa — darhol yuklaymiz
            bot.cached_weather = await bot.fetch_weather_data()
        if bot.cached_weather:
            data = bot.cached_weather
            formatted_date = bot.get_formatted_date()
            periods = ['m', 'd', 'e', 'n']
            temps = {}
            emojis = {}
            for p in periods:
                cond = data.periods.get(p, {}).get('condition', 'N/A')
                uz_cond = bot.translate_weather_condition(cond)
                emojis[f"{p}_emoji"] = bot.get_weather_emoji(uz_cond)
                
                raw_temp = data.periods.get(p, {}).get('temp', 'N/A')
                clean = raw_temp.replace('°', '').replace('C', '').strip()
                match = re.match(r'([+-]?\d+)', clean)
                temps[f"{p}_temp"] = f"{match.group(1)}°" if match else raw_temp

            w_dict = {
                'date': formatted_date, 'location': SETTINGS['default_city'],
                'morning_emoji': emojis['m_emoji'], 'morning_temp': temps['m_temp'],
                'day_emoji': emojis['d_emoji'], 'day_temp': temps['d_temp'],
                'evening_emoji': emojis['e_emoji'], 'evening_temp': temps['e_temp'],
                'night_emoji': emojis['n_emoji'], 'night_temp': temps['n_temp']
            }
            response = bot.format_weather_data_md(w_dict)
        else:
            response = "⚠️ Ob-havo ma'lumotini hozir olishning iloji bo'lmadi. Birozdan keyin qayta urinib ko'ring."

        inline_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 3 kunlik ob-havoni ko'rish", callback_data="weather_3days")]
        ])
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN, reply_markup=inline_kb)

    # 4. Havo tozaligi
    elif "Havo tozaligi" in text:
        await send_typing_action(chat_id, context)
        if not bot.cached_air:  # Cache bo'sh bo'lsa — darhol yuklaymiz
            bot.cached_air = await bot.fetch_air_quality()
        if bot.cached_air:
            data = bot.cached_air
            rec = bot.get_recommendations(data.aqi)
            a_dict = {
                'date': bot.get_formatted_date(),
                'location': 'Toshkent shahri',
                'aqi': data.aqi,
                'advice': rec
            }
            response = bot.format_air_quality_md(a_dict)
        else:
            response = "⚠️ Havo sifati ma'lumotini hozir olishning iloji bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard())

    # 5. Magnit bo'roni
    elif "Magnit" in text:
        await send_typing_action(chat_id, context)
        if not bot.cached_magnetic:  # Cache bo'sh bo'lsa — darhol yuklaymiz
            bot.cached_magnetic = await bot.fetch_magnetic_storms()
        if bot.cached_magnetic:
            response = bot.format_magnetic_data(bot.cached_magnetic)
        else:
            response = "⚠️ Magnit bo'roni ma'lumotini hozir olishning iloji bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        
        inline_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 3 kunlik holatni ko'rish", callback_data="magnetic_3days")]
        ])
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN, reply_markup=inline_kb)

    else:
        await update.message.reply_text("Iltimos, pastdagi tugmalardan birini tanlang 👇", reply_markup=get_main_keyboard())


async def post_init(application: Application):
    try:
        await bot.create_session()
        # Fon vazifasini saqlaymiz — to'xtaganda toza bekor qilish uchun
        bot.background_task = asyncio.create_task(bot.start_background_tasks())
        logger.info("Bot ishga tushdi va background tasklar boshlandi")
    except Exception as e:
        logger.error(f"Start error: {e}")

async def post_stop(application: Application):
    try:
        # Fon vazifasini toza bekor qilamiz ("Task was destroyed" ogohlantirishi bo'lmasligi uchun)
        if bot.background_task and not bot.background_task.done():
            bot.background_task.cancel()
            try:
                await bot.background_task
            except asyncio.CancelledError:
                pass
        await bot.close_session()
        logger.info("Bot to'xtadi")
    except Exception as e:
        logger.error(f"Stop error: {e}")

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN kiritilmagan!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(inline_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.post_init = post_init
    application.post_stop = post_stop

    port = int(os.getenv("PORT", "0"))
    # Render avtomatik beradigan tashqi manzil (yoki qo'lda WEBHOOK_URL)
    webhook_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL")

    if port and webhook_url:
        # ===== PRODUCTION (Render): WEBHOOK rejimi =====
        # Telegram xabarni to'g'ridan-to'g'ri shu manzilga yuboradi → uxlab yotgan
        # servis uyg'onadi. Tashqi ping (keep-alive) shart emas.
        webhook_url = webhook_url.rstrip("/")
        # URL yo'li va maxfiy token uchun faqat ruxsat etilgan belgilar
        secret_path = "".join(
            ch for ch in BOT_TOKEN.split(":")[-1] if ch.isalnum() or ch in "-_"
        )
        logger.info(f"🌐 Webhook rejimida ishga tushmoqda: {webhook_url}")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=secret_path,
            webhook_url=f"{webhook_url}/{secret_path}",
            secret_token=secret_path,
            # MUHIM: False — servis uxlab uyg'onganda, uni uyg'otgan xabar
            # navbatdan o'chirilmasin (aks holda 1-xabarga javob kelmaydi).
            drop_pending_updates=False,
        )
    else:
        # ===== LOKAL: POLLING rejimi =====
        print("✅ Bot lokal polling rejimida ishga tushdi")
        application.run_polling()

if __name__ == '__main__':
    main()