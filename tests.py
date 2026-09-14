import unittest
import logging
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import bot as bot_module
from bot import SuperUzbekBot, PrayerData, PrayerTime, CurrencyData, AirQualityData, WeatherData, MagneticData, cache, tashkent_now, AIR_QUALITY_CACHE_TIME, prayer_cache_seconds_until_refresh, redact_sensitive_text
import asyncio
from datetime import datetime, timezone

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

    def test_logging_does_not_write_files_or_expose_secrets(self):
        file_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, logging.FileHandler)
        ]
        message = (
            "https://api.telegram.org/bot123456:SECRET/getUpdates"
            "?token=my-token&key=my-api-key"
        )
        redacted = redact_sensitive_text(message)

        self.assertEqual(file_handlers, [])
        self.assertNotIn("123456:SECRET", redacted)
        self.assertNotIn("my-token", redacted)
        self.assertNotIn("my-api-key", redacted)
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)

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

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_magnetic_storms_parses_gismeteo_geomagnetic_row(self, mock_fetch):
        mock_fetch.return_value = """
        <div class="widget-row-datetime-time">
            <div class="row-item"><time-value timestamp="1786924800"></time-value></div>
            <div class="row-item"><time-value timestamp="1786935600"></time-value></div>
        </div>
        <div class="widget-row-geomagnetic">
            <div class="row-item"><div class="item item-2">2</div></div>
            <div class="row-item"><div class="item item-5">5</div></div>
        </div>
        """

        result = asyncio.run(self.bot.fetch_magnetic_storms())

        self.assertIsNotNone(result)
        self.assertEqual(
            result.hourly_data,
            [
                {"time": "05:00", "index": "2"},
                {"time": "08:00", "index": "5"},
            ],
        )

    @patch("bot.tashkent_now")
    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_3day_magnetic_forecast_uses_daily_maximum(self, mock_fetch, mock_now):
        mock_now.return_value = datetime(2026, 8, 17, 12, 0, 0)
        mock_fetch.return_value = """
        <div class="widget-row-tod-date">
            <a class="row-item">17 avgust</a>
            <a class="row-item">18 avgust</a>
            <a class="row-item">19 avgust</a>
        </div>
        <div class="widget-row-geomagnetic">
            <div class="row-item"><div class="item">2</div></div>
            <div class="row-item"><div class="item">3</div></div>
            <div class="row-item"><div class="item">4</div></div>
            <div class="row-item"><div class="item">5</div></div>
            <div class="row-item"><div class="item">3</div></div>
            <div class="row-item"><div class="item">4</div></div>
            <div class="row-item"><div class="item">5</div></div>
            <div class="row-item"><div class="item">6</div></div>
            <div class="row-item"><div class="item">4</div></div>
            <div class="row-item"><div class="item">5</div></div>
            <div class="row-item"><div class="item">6</div></div>
            <div class="row-item"><div class="item">7</div></div>
        </div>
        """

        result = asyncio.run(self.bot.fetch_3day_magnetic_forecast())

        self.assertIn("🧲 *3 kunlik magnit prognozi*", result)
        self.assertIn("📍 Toshkent", result)
        self.assertIn("📅 *Bugun · 17-avgust, 2026*", result)
        self.assertIn("🟡 Kuchsiz bo'ron", result)
        self.assertIn("📅 *Ertaga · 18-avgust, 2026*", result)
        self.assertIn("🟠 O'rtacha bo'ron", result)
        self.assertIn("📅 *Indinga · 19-avgust, 2026*", result)
        self.assertIn("🔴 Kuchli bo'ron", result)
        self.assertIn("_Ma'lumot gismeteo.ru saytidan olindi_", result)
        self.assertNotIn("K-indeks:", result)
        self.assertNotIn("━━━━━━━━", result)
        self.assertNotIn("K-indeks oshgan sari", result)
        self.assertNotIn("0–4", result)
        self.assertNotIn("-ball", result)

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

    def test_get_weather_emoji_matches_condition(self):
        cases = {
            "Ochiq": "☀️",
            "Quyoshli": "☀️",
            "Ochiq bulutli": "🌤️",
            "Bulutli": "☁️",
            "Yengil yomg'ir": "🌧️",
            "Qor": "❄️",
            "Yomg'ir va qor": "🌨️",
            "Tuman": "🌫️",
            "Momaqaldiroq": "🌩️",
        }

        for condition, expected in cases.items():
            with self.subTest(condition=condition):
                self.assertEqual(self.bot.get_weather_emoji(condition), expected)

    @patch('bot.SuperUzbekBot.fetch_with_retry', new_callable=AsyncMock)
    def test_fetch_3day_forecast_uses_condition_emoji(self, mock_fetch):
        mock_fetch.return_value = """
        <article class="AppForecastDay_container__AnH4J">
            <h3 class="AppForecastDayHeader_dayTitle__23ecF">Bugun, 17-avgust</h3>
            <div style="grid-area:d-temp">+34°</div>
            <div style="grid-area:n-temp">+25°</div>
            <div style="grid-area:d-text">Ochiq</div>
        </article>
        """

        result = asyncio.run(self.bot.fetch_3day_forecast())

        self.assertIn("☀️ Ochiq", result)
        self.assertNotIn("☁️ Ochiq", result)


class TestAutomaticNotificationSettings(unittest.TestCase):
    """Per-user daily notification configuration and persistence contract."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings_path = Path(self.temp_dir.name) / "notification-settings.json"

    def make_store(self):
        return bot_module.NotificationSettingsStore(self.settings_path)

    def test_main_keyboard_contains_automatic_notification_settings_button(self):
        markup = bot_module.get_main_keyboard()
        button_texts = [button.text for row in markup.keyboard for button in row]

        self.assertIn("⚙️ Avtomatik xabarlar", button_texts)

    def test_setting_is_persisted_and_reloaded(self):
        store = self.make_store()
        saved = store.upsert(
            user_id=101,
            chat_id=202,
            kind="prayer",
            time_str="07:00",
            enabled=True,
        )

        reloaded = self.make_store().get(user_id=101, kind="prayer")

        self.assertEqual(saved, reloaded)
        self.assertEqual(reloaded.user_id, 101)
        self.assertEqual(reloaded.chat_id, 202)
        self.assertEqual(reloaded.kind, "prayer")
        self.assertEqual(reloaded.time_str, "07:00")
        self.assertTrue(reloaded.enabled)
        self.assertIsNone(reloaded.last_sent_date)

    def test_setting_value_object_is_immutable(self):
        setting = self.make_store().upsert(
            user_id=101,
            chat_id=202,
            kind="weather",
            time_str="08:00",
        )

        with self.assertRaises(FrozenInstanceError):
            setting.time_str = "09:00"

    def test_upsert_rejects_invalid_boundary_values(self):
        store = self.make_store()

        invalid_values = [
            {"user_id": True, "chat_id": 202, "kind": "prayer", "time_str": "07:00"},
            {"user_id": 0, "chat_id": 202, "kind": "prayer", "time_str": "07:00"},
            {"user_id": 101, "chat_id": False, "kind": "prayer", "time_str": "07:00"},
            {"user_id": 101, "chat_id": 0, "kind": "prayer", "time_str": "07:00"},
            {"user_id": 101, "chat_id": 202, "kind": "news", "time_str": "07:00"},
            {"user_id": 101, "chat_id": 202, "kind": "prayer", "time_str": "7:00"},
            {"user_id": 101, "chat_id": 202, "kind": "prayer", "time_str": "24:00"},
            {"user_id": 101, "chat_id": 202, "kind": "prayer", "time_str": "07:60"},
        ]

        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                store.upsert(**values)

    def test_get_rejects_invalid_boundary_values(self):
        store = self.make_store()

        invalid_values = [
            (True, "prayer"),
            (0, "prayer"),
            (101, "news"),
        ]
        for user_id, kind in invalid_values:
            with self.subTest(user_id=user_id, kind=kind), self.assertRaises(ValueError):
                store.get(user_id, kind)

    def test_callback_parser_accepts_only_supported_actions_and_values(self):
        supported_kinds = ("prayer", "weather", "currency", "air", "magnetic")
        for index, kind in enumerate(supported_kinds, start=7):
            time_str = f"{index:02d}:00"
            with self.subTest(kind=kind):
                self.assertEqual(
                    bot_module.parse_notification_callback(
                        f"notify:set:{kind}:{time_str}"
                    ),
                    {"action": "set", "kind": kind, "time": time_str},
                )

        self.assertEqual(
            bot_module.parse_notification_callback("notify:toggle:weather:off"),
            {"action": "toggle", "kind": "weather", "enabled": False},
        )
        self.assertEqual(
            bot_module.parse_notification_callback("notify:toggle:prayer:on"),
            {"action": "toggle", "kind": "prayer", "enabled": True},
        )

        invalid_callbacks = [
            "weather:set:prayer:07:00",
            "notify:delete:prayer:07:00",
            "notify:set:news:07:00",
            "notify:set:prayer:7:00",
            "notify:set:prayer:24:00",
            "notify:toggle:prayer:yes",
            "notify:set:prayer:07:00:ignored",
        ]
        for callback_data in invalid_callbacks:
            with self.subTest(callback_data=callback_data), self.assertRaises(ValueError):
                bot_module.parse_notification_callback(callback_data)

    def test_disable_and_enable_are_persistent_and_preserve_time(self):
        store = self.make_store()
        store.upsert(101, 202, "prayer", "07:00", enabled=True)

        disabled = store.set_enabled(101, "prayer", False)
        disabled_after_restart = self.make_store().get(101, "prayer")

        self.assertFalse(disabled.enabled)
        self.assertEqual(disabled.time_str, "07:00")
        self.assertFalse(disabled_after_restart.enabled)

        enabled = self.make_store().set_enabled(101, "prayer", True)
        self.assertTrue(enabled.enabled)
        self.assertEqual(enabled.time_str, "07:00")

    def test_due_matching_uses_asia_tashkent_with_restart_grace_window(self):
        store = self.make_store()
        store.upsert(101, 202, "prayer", "07:00")
        store.upsert(101, 202, "weather", "08:00")

        # 02:00 UTC is 07:00 in Asia/Tashkent.
        due = store.due_at(datetime(2026, 9, 14, 2, 0, 45, tzinfo=timezone.utc))
        shortly_after = store.due_at(datetime(2026, 9, 14, 2, 1, tzinfo=timezone.utc))
        too_late = store.due_at(datetime(2026, 9, 14, 2, 15, tzinfo=timezone.utc))

        self.assertEqual([(item.user_id, item.kind) for item in due], [(101, "prayer")])
        self.assertEqual(
            [(item.user_id, item.kind) for item in shortly_after],
            [(101, "prayer")],
        )
        self.assertEqual(too_late, [])

    def test_due_matching_rejects_naive_datetime(self):
        store = self.make_store()
        store.upsert(101, 202, "prayer", "07:00")

        with self.assertRaises(ValueError):
            store.due_at(datetime(2026, 9, 14, 7, 0))

    def test_disabled_setting_is_not_due(self):
        store = self.make_store()
        store.upsert(101, 202, "prayer", "07:00", enabled=False)

        due = store.due_at(datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc))

        self.assertEqual(due, [])

    def test_mark_sent_prevents_duplicate_only_for_same_local_day(self):
        store = self.make_store()
        store.upsert(101, 202, "prayer", "07:00")
        first_day = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)

        store.mark_sent(101, "prayer", first_day)

        self.assertEqual(store.due_at(first_day), [])
        next_day = datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(
            [(item.user_id, item.kind) for item in store.due_at(next_day)],
            [(101, "prayer")],
        )


class TestAutomaticNotificationDispatch(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = bot_module.NotificationSettingsStore(
            Path(self.temp_dir.name) / "notification-settings.json"
        )
        self.provider = MagicMock()
        self.provider.build_prayer_notification = AsyncMock(return_value="prayer text")
        self.provider.build_weather_notification = AsyncMock(return_value="weather text")
        self.provider.build_currency_notification = AsyncMock(return_value="currency text")
        self.provider.build_air_notification = AsyncMock(return_value="air text")
        self.provider.build_magnetic_notification = AsyncMock(return_value="magnetic text")
        self.sender = MagicMock()
        self.sender.send_message = AsyncMock()
        self.service = bot_module.AutomaticNotificationService(self.store, self.provider)

    async def test_dispatch_uses_all_existing_content_interfaces(self):
        schedules = (
            (101, 201, "prayer", "prayer text"),
            (102, 202, "weather", "weather text"),
            (103, 203, "currency", "currency text"),
            (104, 204, "air", "air text"),
            (105, 205, "magnetic", "magnetic text"),
        )
        for user_id, chat_id, kind, _ in schedules:
            self.store.upsert(user_id, chat_id, kind, "07:00")
        now = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)

        sent_count = await self.service.dispatch_due(self.sender, now)

        self.assertEqual(sent_count, 5)
        self.provider.build_prayer_notification.assert_awaited_once_with()
        self.provider.build_weather_notification.assert_awaited_once_with()
        self.provider.build_currency_notification.assert_awaited_once_with()
        self.provider.build_air_notification.assert_awaited_once_with()
        self.provider.build_magnetic_notification.assert_awaited_once_with()
        for _, chat_id, _, text in schedules:
            self.sender.send_message.assert_any_await(
                chat_id=chat_id,
                text=text,
                parse_mode=bot_module.ParseMode.MARKDOWN,
            )

    async def test_dispatch_does_not_send_twice_on_same_day(self):
        self.store.upsert(101, 201, "prayer", "07:00")
        now = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)

        first_count = await self.service.dispatch_due(self.sender, now)
        second_count = await self.service.dispatch_due(self.sender, now)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.sender.send_message.assert_awaited_once()

    async def test_failed_send_is_not_marked_and_can_be_retried(self):
        self.store.upsert(101, 201, "weather", "08:00")
        now = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
        self.sender.send_message.side_effect = RuntimeError("Telegram unavailable")

        sent_count = await self.service.dispatch_due(self.sender, now)

        self.assertEqual(sent_count, 0)
        self.assertEqual(
            [(item.user_id, item.kind) for item in self.store.due_at(now)],
            [(101, "weather")],
        )

    async def test_failed_data_fetch_message_is_not_sent_or_marked(self):
        self.store.upsert(101, 201, "weather", "08:00")
        now = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
        self.provider.build_weather_notification.return_value = (
            "⚠️ Ob-havo ma'lumotini hozir olishning iloji bo'lmadi."
        )

        sent_count = await self.service.dispatch_due(self.sender, now)

        self.assertEqual(sent_count, 0)
        self.sender.send_message.assert_not_awaited()
        self.assertEqual(
            [(item.user_id, item.kind) for item in self.store.due_at(now)],
            [(101, "weather")],
        )

if __name__ == '__main__':
    unittest.main()
