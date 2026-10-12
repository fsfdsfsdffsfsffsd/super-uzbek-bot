-- Run after NOTIFICATION_DATABASE_URL is configured and the bot has initialized its table.
-- No bot tokens or database passwords are sent in the public wake-up request.
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

CREATE OR REPLACE FUNCTION bot_private.wake_for_notifications()
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    local_now TIMESTAMP := CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tashkent';
    request_id BIGINT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM bot_private.notification_settings AS s
        CROSS JOIN LATERAL (
            SELECT local_now::date + s.time_str::time AS scheduled_at
        ) AS schedule
        WHERE s.enabled AND (
            -- Unsent today: wake just before the time or after downtime.
            ((s.last_sent_date IS NULL OR s.last_sent_date < local_now::date)
             AND schedule.scheduled_at <= local_now + INTERVAL '3 minutes'
             AND (s.next_attempt_at IS NULL OR s.next_attempt_at <= CURRENT_TIMESTAMP))
            OR
            -- Also pre-wake for tomorrow's midnight notifications.
            (schedule.scheduled_at + INTERVAL '1 day' BETWEEN local_now AND local_now + INTERVAL '3 minutes'
             AND (s.last_sent_date IS NULL OR s.last_sent_date < local_now::date + 1))
        )
    ) THEN
        SELECT net.http_get(
            url := 'https://super-uzbek-bot.onrender.com/',
            timeout_milliseconds := 10000
        ) INTO request_id;
    END IF;
    RETURN request_id;
END;
$$;

-- Re-running this named schedule updates it instead of adding duplicates.
SELECT cron.schedule(
    'super-uzbek-notifications-wake',
    '* * * * *',
    'SELECT bot_private.wake_for_notifications();'
);
