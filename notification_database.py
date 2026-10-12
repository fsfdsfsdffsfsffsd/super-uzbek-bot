"""Durable notification storage in a private PostgreSQL schema."""

from datetime import datetime, timedelta
from typing import Optional

import certifi
import psycopg
from psycopg.rows import dict_row

from notifications import (
    NotificationSetting,
    NotificationSettingsStore,
    NOTIFICATION_RETRY_MINUTES,
    _TASHKENT_TZ,
    _validate_aware_datetime,
    _validate_setting_values,
)


class NotificationStorageError(OSError):
    """Safe public error: database credentials must not appear in exceptions/logs."""


class PostgresNotificationSettingsStore(NotificationSettingsStore):
    """Per-row writes preserve other users' settings during overlapping deploys."""

    def __init__(self, database_url: str, certificate_file: Optional[str] = None):
        self._database_url = database_url
        self._certificate_file = certificate_file or certifi.where()

    def _query(self, sql: str, parameters: tuple = ()) -> list[dict]:
        try:
            with psycopg.connect(
                self._database_url,
                connect_timeout=10,
                sslmode="verify-full",
                sslrootcert=self._certificate_file,
                row_factory=dict_row,
                prepare_threshold=None,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 10000")
                    cursor.execute(sql, parameters)
                    return cursor.fetchall() if cursor.description else []
        except psycopg.Error:
            raise NotificationStorageError("Avtomatik xabarlar bazasi bilan ulanishda xatolik") from None

    def initialize(self) -> None:
        self._query("CREATE SCHEMA IF NOT EXISTS bot_private")
        self._query("""
            CREATE TABLE IF NOT EXISTS bot_private.notification_settings (
                user_id BIGINT NOT NULL CHECK (user_id > 0),
                chat_id BIGINT NOT NULL CHECK (chat_id <> 0),
                kind TEXT NOT NULL CHECK (kind IN ('prayer', 'weather', 'currency', 'air', 'magnetic')),
                time_str TEXT NOT NULL CHECK (time_str ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                last_sent_date DATE,
                next_attempt_at TIMESTAMPTZ,
                PRIMARY KEY (user_id, kind)
            )
        """)

    @staticmethod
    def _setting(row: dict) -> NotificationSetting:
        values = {key: row[key] for key in (
            "user_id", "chat_id", "kind", "time_str", "enabled", "last_sent_date"
        )}
        if values["last_sent_date"] is not None:
            values["last_sent_date"] = values["last_sent_date"].isoformat()
        return NotificationSetting(**values)

    def all(self) -> tuple[NotificationSetting, ...]:
        return tuple(self._setting(row) for row in self._query(
            "SELECT * FROM bot_private.notification_settings ORDER BY user_id, kind"
        ))

    def get(self, user_id: int, kind: str) -> Optional[NotificationSetting]:
        _validate_setting_values(user_id, 1, kind, "00:00")
        rows = self._query(
            "SELECT * FROM bot_private.notification_settings WHERE user_id = %s AND kind = %s",
            (user_id, kind),
        )
        return self._setting(rows[0]) if rows else None

    def for_user(self, user_id: int) -> tuple[NotificationSetting, ...]:
        _validate_setting_values(user_id, 1, "prayer", "00:00")
        return tuple(self._setting(row) for row in self._query(
            "SELECT * FROM bot_private.notification_settings WHERE user_id = %s ORDER BY kind",
            (user_id,),
        ))

    def upsert(
        self, user_id: int, chat_id: int, kind: str, time_str: str,
        enabled: bool = True, activated_at: Optional[datetime] = None,
    ) -> NotificationSetting:
        _validate_setting_values(user_id, chat_id, kind, time_str)
        if not isinstance(enabled, bool):
            raise ValueError("enabled boolean bo'lishi kerak")
        skipped_date = None
        if activated_at is not None:
            _validate_aware_datetime(activated_at)
            local_now = activated_at.astimezone(_TASHKENT_TZ)
            if local_now.strftime("%H:%M") >= time_str:
                skipped_date = local_now.date()
        rows = self._query("""
            INSERT INTO bot_private.notification_settings
                (user_id, chat_id, kind, time_str, enabled, last_sent_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, kind) DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                time_str = EXCLUDED.time_str,
                enabled = EXCLUDED.enabled,
                last_sent_date = COALESCE(
                    GREATEST(notification_settings.last_sent_date, EXCLUDED.last_sent_date),
                    notification_settings.last_sent_date
                )
            RETURNING *
        """, (user_id, chat_id, kind, time_str, enabled, skipped_date))
        return self._setting(rows[0])

    def set_enabled(self, user_id: int, kind: str, enabled: bool) -> NotificationSetting:
        _validate_setting_values(user_id, 1, kind, "00:00")
        if not isinstance(enabled, bool):
            raise ValueError("enabled boolean bo'lishi kerak")
        rows = self._query("""
            UPDATE bot_private.notification_settings SET enabled = %s
            WHERE user_id = %s AND kind = %s RETURNING *
        """, (enabled, user_id, kind))
        if not rows:
            raise KeyError("Sozlama topilmadi")
        return self._setting(rows[0])

    def mark_sent(self, user_id: int, kind: str, sent_at: datetime) -> NotificationSetting:
        _validate_aware_datetime(sent_at)
        _validate_setting_values(user_id, 1, kind, "00:00")
        rows = self._query("""
            UPDATE bot_private.notification_settings
            SET last_sent_date = GREATEST(last_sent_date, %s), next_attempt_at = NULL
            WHERE user_id = %s AND kind = %s RETURNING *
        """, (sent_at.astimezone(_TASHKENT_TZ).date(), user_id, kind))
        if not rows:
            raise KeyError("Sozlama topilmadi")
        return self._setting(rows[0])

    def due_at(self, now: datetime) -> list[NotificationSetting]:
        _validate_aware_datetime(now)
        local_now = now.astimezone(_TASHKENT_TZ)
        return [self._setting(row) for row in self._query("""
            SELECT * FROM bot_private.notification_settings
            WHERE enabled = TRUE AND time_str <= %s
                AND (last_sent_date IS NULL OR last_sent_date < %s)
                AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY user_id, kind
        """, (local_now.strftime("%H:%M"), local_now.date(), now))]

    def claim_due(self, user_id: int, kind: str, now: datetime) -> bool:
        """Persist retry cooldown atomically so overlapping deployments cannot both send."""
        _validate_aware_datetime(now)
        _validate_setting_values(user_id, 1, kind, "00:00")
        local_now = now.astimezone(_TASHKENT_TZ)
        rows = self._query("""
            UPDATE bot_private.notification_settings SET next_attempt_at = %s
            WHERE user_id = %s AND kind = %s AND enabled = TRUE
                AND time_str <= %s AND (last_sent_date IS NULL OR last_sent_date < %s)
                AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            RETURNING user_id
        """, (
            now + timedelta(minutes=NOTIFICATION_RETRY_MINUTES),
            user_id, kind, local_now.strftime("%H:%M"), local_now.date(), now,
        ))
        return bool(rows)
