-- Disposable fixture: all writes are rolled back before another connection can see them.
BEGIN;
DO $$
DECLARE
    fixture_user CONSTANT BIGINT := 9223372036854700001;
    local_today DATE := (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tashkent')::date;
    affected INTEGER;
BEGIN
    ASSERT to_regclass('bot_private.notification_settings') IS NOT NULL, 'Bot table not initialized';
    ASSERT NOT EXISTS (
        SELECT 1 FROM bot_private.notification_settings WHERE user_id = fixture_user
    ), 'Fixture ID already exists';

    INSERT INTO bot_private.notification_settings
        (user_id, chat_id, kind, time_str, enabled, last_sent_date)
    VALUES (fixture_user, fixture_user, 'weather', '00:00', TRUE, NULL);
    ASSERT EXISTS (
        SELECT 1 FROM bot_private.notification_settings
        WHERE user_id = fixture_user AND kind = 'weather' AND time_str = '00:00'
    ), 'Round-trip read failed';

    UPDATE bot_private.notification_settings SET next_attempt_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes'
    WHERE user_id = fixture_user AND kind = 'weather' AND enabled
        AND (last_sent_date IS NULL OR last_sent_date < local_today)
        AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP);
    GET DIAGNOSTICS affected = ROW_COUNT;
    ASSERT affected = 1, 'First claim failed';

    UPDATE bot_private.notification_settings SET next_attempt_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes'
    WHERE user_id = fixture_user AND kind = 'weather' AND enabled
        AND (last_sent_date IS NULL OR last_sent_date < local_today)
        AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP);
    GET DIAGNOSTICS affected = ROW_COUNT;
    ASSERT affected = 0, 'Parallel claim would duplicate a message';

    UPDATE bot_private.notification_settings
    SET last_sent_date = GREATEST(last_sent_date, local_today), next_attempt_at = NULL
    WHERE user_id = fixture_user AND kind = 'weather';

    INSERT INTO bot_private.notification_settings
        (user_id, chat_id, kind, time_str, enabled, last_sent_date)
    VALUES (fixture_user, fixture_user, 'weather', '00:00', TRUE, NULL)
    ON CONFLICT (user_id, kind) DO UPDATE SET
        time_str = EXCLUDED.time_str,
        last_sent_date = COALESCE(
            GREATEST(notification_settings.last_sent_date, EXCLUDED.last_sent_date),
            notification_settings.last_sent_date
        );
    ASSERT EXISTS (
        SELECT 1 FROM bot_private.notification_settings
        WHERE user_id = fixture_user AND last_sent_date = local_today
    ), 'Updating time erased sent date';
    ASSERT NOT EXISTS (
        SELECT 1 FROM bot_private.notification_settings
        WHERE user_id = fixture_user AND enabled
            AND (last_sent_date IS NULL OR last_sent_date < local_today)
    ), 'Delivered setting is still due';
END;
$$;
ROLLBACK;
SELECT 'PostgreSQL round-trip, claim and duplicate checks passed; fixture rolled back' AS result;
