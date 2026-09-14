"""Persistent per-user daily notification settings and dispatch."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

from telegram.constants import ParseMode


logger = logging.getLogger(__name__)

SUPPORTED_NOTIFICATION_KINDS = frozenset(
    {"prayer", "weather", "currency", "air", "magnetic"}
)
_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_TASHKENT_TZ = timezone(timedelta(hours=5), "Asia/Tashkent")
NOTIFICATION_GRACE_MINUTES = 15


@dataclass(frozen=True)
class NotificationSetting:
    user_id: int
    chat_id: int
    kind: str
    time_str: str
    enabled: bool = True
    last_sent_date: Optional[str] = None


class NotificationProvider(Protocol):
    async def build_prayer_notification(self) -> str: ...

    async def build_weather_notification(self) -> str: ...

    async def build_currency_notification(self) -> str: ...

    async def build_air_notification(self) -> str: ...

    async def build_magnetic_notification(self) -> str: ...


def _validate_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Vaqt timezone bilan berilishi kerak")


def _validate_setting_values(
    user_id: int,
    chat_id: int,
    kind: str,
    time_str: str,
) -> None:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("Noto'g'ri foydalanuvchi ID")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool) or chat_id == 0:
        raise ValueError("Noto'g'ri chat ID")
    if kind not in SUPPORTED_NOTIFICATION_KINDS:
        raise ValueError("Noma'lum xabar turi")
    if not isinstance(time_str, str) or not _TIME_PATTERN.fullmatch(time_str):
        raise ValueError("Vaqt HH:MM formatida bo'lishi kerak")


def parse_notification_callback(data: str) -> dict[str, Any]:
    """Parse and strictly validate state-changing notification callbacks."""
    if not isinstance(data, str):
        raise ValueError("Noto'g'ri callback")

    parts = data.split(":", 3)
    if len(parts) != 4 or parts[0] != "notify":
        raise ValueError("Noto'g'ri callback")

    _, action, kind, value = parts
    if kind not in SUPPORTED_NOTIFICATION_KINDS:
        raise ValueError("Noma'lum xabar turi")

    if action == "set":
        if not _TIME_PATTERN.fullmatch(value):
            raise ValueError("Noto'g'ri vaqt")
        return {"action": "set", "kind": kind, "time": value}

    if action == "toggle" and value in {"on", "off"}:
        return {"action": "toggle", "kind": kind, "enabled": value == "on"}

    raise ValueError("Noma'lum amal")


class NotificationSettingsStore:
    """Small atomic JSON store suitable for one bot process."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _key(user_id: int, kind: str) -> str:
        return f"{user_id}:{kind}"

    def _load_unlocked(self) -> dict[str, NotificationSetting]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Avtomatik xabar sozlamalarini o'qib bo'lmadi: %s", exc)
            return {}

        raw_items = payload.get("settings", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_items, dict):
            logger.error("Avtomatik xabar sozlamalari formati noto'g'ri")
            return {}

        result: dict[str, NotificationSetting] = {}
        for raw in raw_items.values():
            try:
                if not isinstance(raw, dict):
                    raise ValueError("Sozlama obyekt emas")
                setting = NotificationSetting(
                    user_id=raw["user_id"],
                    chat_id=raw["chat_id"],
                    kind=raw["kind"],
                    time_str=raw["time_str"],
                    enabled=raw.get("enabled", True),
                    last_sent_date=raw.get("last_sent_date"),
                )
                _validate_setting_values(
                    setting.user_id,
                    setting.chat_id,
                    setting.kind,
                    setting.time_str,
                )
                if not isinstance(setting.enabled, bool):
                    raise ValueError("enabled boolean emas")
                result[self._key(setting.user_id, setting.kind)] = setting
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Bitta yaroqsiz avtomatik xabar sozlamasi o'tkazib yuborildi: %s", exc)
        return result

    def _save_unlocked(self, settings: dict[str, NotificationSetting]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "settings": {
                key: asdict(value)
                for key, value in sorted(settings.items())
            },
        }
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
        except OSError:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def all(self) -> tuple[NotificationSetting, ...]:
        with self._lock:
            return tuple(self._load_unlocked().values())

    def get(self, user_id: int, kind: str) -> Optional[NotificationSetting]:
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError("Noto'g'ri foydalanuvchi ID")
        if kind not in SUPPORTED_NOTIFICATION_KINDS:
            raise ValueError("Noma'lum xabar turi")
        with self._lock:
            return self._load_unlocked().get(self._key(user_id, kind))

    def upsert(
        self,
        user_id: int,
        chat_id: int,
        kind: str,
        time_str: str,
        enabled: bool = True,
    ) -> NotificationSetting:
        _validate_setting_values(user_id, chat_id, kind, time_str)
        if not isinstance(enabled, bool):
            raise ValueError("enabled boolean bo'lishi kerak")

        with self._lock:
            settings = self._load_unlocked()
            key = self._key(user_id, kind)
            previous = settings.get(key)
            value = NotificationSetting(
                user_id=user_id,
                chat_id=chat_id,
                kind=kind,
                time_str=time_str,
                enabled=enabled,
                last_sent_date=previous.last_sent_date if previous else None,
            )
            updated = {**settings, key: value}
            self._save_unlocked(updated)
            return value

    def set_enabled(
        self,
        user_id: int,
        kind: str,
        enabled: bool,
    ) -> NotificationSetting:
        if not isinstance(enabled, bool):
            raise ValueError("enabled boolean bo'lishi kerak")
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError("Noto'g'ri foydalanuvchi ID")
        if kind not in SUPPORTED_NOTIFICATION_KINDS:
            raise ValueError("Noma'lum xabar turi")
        with self._lock:
            settings = self._load_unlocked()
            key = self._key(user_id, kind)
            previous = settings.get(key)
            if previous is None:
                raise KeyError("Sozlama topilmadi")
            value = replace(previous, enabled=enabled)
            self._save_unlocked({**settings, key: value})
            return value

    def mark_sent(
        self,
        user_id: int,
        kind: str,
        sent_at: datetime,
    ) -> NotificationSetting:
        _validate_aware_datetime(sent_at)
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError("Noto'g'ri foydalanuvchi ID")
        if kind not in SUPPORTED_NOTIFICATION_KINDS:
            raise ValueError("Noma'lum xabar turi")
        local_date = sent_at.astimezone(_TASHKENT_TZ).date().isoformat()
        with self._lock:
            settings = self._load_unlocked()
            key = self._key(user_id, kind)
            previous = settings.get(key)
            if previous is None:
                raise KeyError("Sozlama topilmadi")
            value = replace(previous, last_sent_date=local_date)
            self._save_unlocked({**settings, key: value})
            return value

    def due_at(self, now: datetime) -> list[NotificationSetting]:
        _validate_aware_datetime(now)
        local_now = now.astimezone(_TASHKENT_TZ)
        local_date = local_now.date().isoformat()
        due = []
        for item in self.all():
            scheduled_hour, scheduled_minute = map(int, item.time_str.split(":"))
            scheduled_at = local_now.replace(
                hour=scheduled_hour,
                minute=scheduled_minute,
                second=0,
                microsecond=0,
            )
            elapsed = local_now - scheduled_at
            if (
                item.enabled
                and item.last_sent_date != local_date
                and timedelta(0) <= elapsed < timedelta(minutes=NOTIFICATION_GRACE_MINUTES)
            ):
                due.append(item)
        return sorted(due, key=lambda item: (item.user_id, item.kind))


class AutomaticNotificationService:
    def __init__(self, store: NotificationSettingsStore, provider: NotificationProvider):
        self.store = store
        self.provider = provider

    async def dispatch_due(self, sender: Any, now: datetime) -> int:
        due = self.store.due_at(now)
        messages: dict[str, str] = {}
        sent_count = 0

        for setting in due:
            try:
                if setting.kind not in messages:
                    builder = getattr(
                        self.provider,
                        f"build_{setting.kind}_notification",
                    )
                    messages = {**messages, setting.kind: await builder()}
                text = messages[setting.kind]
                if not text or text.startswith(("⚠️", "❌")):
                    continue
                await sender.send_message(
                    chat_id=setting.chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                )
                self.store.mark_sent(setting.user_id, setting.kind, now)
                sent_count += 1
            except Exception as exc:
                logger.error(
                    "Avtomatik %s xabari yuborilmadi: %s",
                    setting.kind,
                    exc,
                )
        return sent_count
