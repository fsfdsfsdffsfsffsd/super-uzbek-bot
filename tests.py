import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from bot import SuperUzbekBot, PrayerData, PrayerTime, CurrencyData, AirQualityData, WeatherData, MagneticData, cache, tashkent_now, AIR_QUALITY_CACHE_TIME, prayer_cache_seconds_until_refresh
import asyncio
from datetime import datetime

class TestSuperUzbekBot(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.bot = SuperUzbekBot()
        # Mock session creation to avoid actual network init
        self.bot.session = MagicMock()

    def test_tashkent_now_uses_utc_plus_five(self):
        now = tashkent_now()

        self.assertEqual(now.tzname(), "Asia/Tashkent")
        self.assertEqual(now.utcoffset().total_seconds(), 5 * 60 * 60)

    def test_prayer_cache_expires_at_next_midnight(self):
        seconds = prayer_cache_seconds_until_refresh(datetime(2026, 7, 16, 1, 0, 0))

        self.assertEqual(seconds, 23 * 60 * 60)

    def test_prayer_cache_before_midnight_expires_today(self):
        seconds = prayer_cache_seconds_until_refresh(datetime(2026, 7, 16, 23, 59, 30))

        self.assertEqual(seconds, 30)

    @patch("bot.tashkent_now")
    def test_format_magnetic_data_matches_compact_design(self, mock_now):
        mock_now.return_value = datetime(2026, 7, 19, 12, 0, 0)
        data = MagneticData(
            date="Bugun",
            hourly_data=[
                {"time": "2:00", "index": "4"},
                {"time": "05:00", "index": "5"},
                {"time": "08:00", "index": "6"},
                {"time": "11:00", "index": "7"},
                {"time": "14:00", "index": "8"},
            ],
            timestamp="19.07.2026 12:00",
        )

        result = self.bot.format_magnetic_data(data)

        self.assertIn("🧲 *Magnit bo'roni*", result)
        self.assertIn("📅 19-iyul, 2026", result)
        self.assertIn("🕘 02:00  🟢", result)
        self.assertIn("🕘 05:00  🟡", result)
        self.assertIn("🕘 08:00  🟠", result)
        self.assertIn("🕘 11:00  🔴", result)
        self.assertIn("🕘 14:00  🟣", result)
        self.assertIn("🟡 Kuchsiz magnit bo'ron", result)
        self.assertNotIn("ball", result)

    def test_format_prayer_times(self):
        data = PrayerData(
            times={
                PrayerTime.BOMDOD: "05:00",
                PrayerTime.QUYOSH: "06:30",
                PrayerTime.PESHIN: "13:00",
                PrayerTime.ASR: "16:00",
                PrayerTime.SHOM: "18:00",
                PrayerTime.XUFTON: "19:30"
            },
            date="01.01.2025",
            hijri_date="1446"
        )
        result = self.bot.format_prayer_times(data)
        self.assertIn("🕌 *Namoz Vaqtlari*", result)
        self.assertIn("*Bomdod:* 05:00", result)
        self.assertIn("*Xufton:* 19:30", result)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_get_prayer_times(self, mock_fetch):
        # Minimal HTML structure based on the bot's parser logic
        html = """
        <div id="prayer">
            <div class="flex-column">
                <div>Бомдод</div>
                <div>05:00</div>
            </div>
            <div class="flex-column">
                <div>Қуёш</div>
                <div>06:30</div>
            </div>
            <div class="flex-column">
                <div>Пешин</div>
                <div>13:00</div>
            </div>
            <div class="flex-column">
                <div>Аср</div>
                <div>16:00</div>
            </div>
            <div class="flex-column">
                <div>Шом</div>
                <div>18:00</div>
            </div>
            <div class="flex-column">
                <div>Хуфтон</div>
                <div>19:30</div>
            </div>
        </div>
        """
        mock_fetch.return_value = html
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.get_prayer_times())
        loop.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result.times[PrayerTime.BOMDOD], "05:00")
        self.assertEqual(result.times[PrayerTime.XUFTON], "19:30")
        self.assertGreater(cache["prayer_times"]["expiry"], 1)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_get_currency_rates(self, mock_fetch):
        html = """
        <div class="bc-inner-blocks-left">
            <div class="bc-inner-block-left-texts">
                <a>Test Bank</a>
                <span class="rate-value">12 500</span>
            </div>
        </div>
        <div class="bc-inner-blocks-right">
            <div class="bc-inner-block-left-texts">
                <a>Test Bank</a>
                <span class="rate-value">12 600</span>
            </div>
        </div>
        """
        mock_fetch.return_value = html
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.get_currency_rates())
        loop.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result.banks), 1)
        self.assertEqual(result.banks[0]['name'], "Test Bank")
        self.assertEqual(result.banks[0]['buy'], 12500.0)
        self.assertEqual(result.banks[0]['sell'], 12600.0)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_air_quality(self, mock_fetch):
        html = """
        <div class="line-clamp-2 flex flex-none flex-col items-center justify-center rounded-md p-2 aqi-legend-bg-yellow">
            <p class="text-lg font-medium">84</p>
            <span class="text-[10px] uppercase">AQI+ США</span>
        </div>
        <div class="level-name">Unhealthy for Sensitive Groups</div>
        <div class="pollutant-name">
            <p>PM2.5</p>
            <p>PM2.5</p>
            <div>45.5 µg/m³</div>
        </div>
        """
        mock_fetch.return_value = html

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.fetch_air_quality())
        loop.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.aqi, "84")
        self.assertEqual(result.quality, "Unhealthy for Sensitive Groups")
        self.assertEqual(cache["air_quality"]["expiry"], AIR_QUALITY_CACHE_TIME)
        mock_fetch.assert_awaited_once_with(
            "https://www.iqair.com/ru/air-quality/uzbekistan/toshkent-shahri/tashkent",
            max_retries=1,
            delay=1,
            request_timeout=8,
        )

    @patch('bot.IQAIR_API_KEY', 'test-key')
    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_air_quality_uses_iqair_api_when_key_is_set(self, mock_fetch):
        mock_fetch.return_value = """
        {
            "status": "success",
            "data": {
                "current": {
                    "pollution": {
                        "aqius": 58,
                        "mainus": "p2"
                    }
                }
            }
        }
        """

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.fetch_air_quality())
        loop.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.aqi, "58")
        self.assertEqual(result.pollutant, "PM2.5")
        self.assertIn("api.airvisual.com/v2/city", mock_fetch.await_args.args[0])

    @patch('bot.IQAIR_API_KEY', 'test-key')
    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_air_quality_reuses_cache_for_ten_minutes(self, mock_fetch):
        mock_fetch.return_value = """
        {
            "status": "success",
            "data": {
                "current": {
                    "pollution": {
                        "aqius": 56,
                        "mainus": "p2"
                    }
                }
            }
        }
        """

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        first = loop.run_until_complete(self.bot.fetch_air_quality())
        second = loop.run_until_complete(self.bot.fetch_air_quality())
        loop.close()

        self.assertEqual(first.aqi, "56")
        self.assertEqual(second.aqi, "56")
        self.assertIs(first, second)
        self.assertEqual(cache["air_quality"]["expiry"], 600)
        self.assertEqual(mock_fetch.await_count, 1)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_air_quality_uses_iqair_fallback_url(self, mock_fetch):
        html = """
        <script type="application/ld+json">
        {
            "@type": "Observation",
            "variableMeasured": [
                {
                    "@type": "PropertyValue",
                    "name": "Air Quality Index (US AQI+)",
                    "value": 77
                }
            ]
        }
        </script>
        """
        mock_fetch.side_effect = [None, html]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.fetch_air_quality())
        loop.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.aqi, "77")
        self.assertEqual(mock_fetch.await_args_list[0].args[0], "https://www.iqair.com/ru/air-quality/uzbekistan/toshkent-shahri/tashkent")
        self.assertEqual(mock_fetch.await_args_list[1].args[0], "https://www.iqair.com/air-quality/uzbekistan/toshkent-shahri/tashkent")
        self.assertEqual(mock_fetch.await_count, 2)

    @patch('bot.SuperUzbekBot.fetch_with_browser_impersonation', new_callable=AsyncMock)
    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_air_quality_uses_browser_fallback(self, mock_fetch, mock_browser_fetch):
        html = """
        <div class="line-clamp-2 flex flex-none flex-col items-center justify-center rounded-md p-2 aqi-legend-bg-yellow">
            <p class="text-lg font-medium">74</p>
            <span class="text-[10px] uppercase">AQI+ РЎРЁРђ</span>
        </div>
        """
        mock_fetch.return_value = None
        mock_browser_fetch.return_value = html

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.fetch_air_quality())
        loop.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.aqi, "74")
        self.assertEqual(mock_browser_fetch.await_count, 1)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_weather_data(self, mock_fetch):
        # Minimal mocked HTML for weather
        html = """
        <article class="AppForecastDay_container__AnH4J">
            <h3 class="AppForecastDayHeader_dayTitle__23ecF">Today</h3>
            <!-- Morning -->
            <div style="grid-area:m-temp">+10</div>
            <div style="grid-area:m-text">Clear</div>
            <!-- Day -->
            <div style="grid-area:d-temp">+20</div>
            <div style="grid-area:d-text">Cloudy</div>
            <!-- Evening -->
            <div style="grid-area:e-temp">+15</div>
            <div style="grid-area:e-text">Rain</div>
            <!-- Night -->
            <div style="grid-area:n-temp">+5</div>
            <div style="grid-area:n-text">Clear</div>
        </article>
        """
        mock_fetch.return_value = html
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.bot.fetch_weather_data())
        loop.close()
        
        self.assertIsNotNone(result)
        self.assertEqual(result.periods['m']['temp'], "+10")
        self.assertEqual(result.periods['d']['condition'], "Cloudy")

if __name__ == '__main__':
    unittest.main()
