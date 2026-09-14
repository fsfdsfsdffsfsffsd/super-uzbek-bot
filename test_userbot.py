import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import userbot


class FakeClient:
    def __init__(self):
        self.calls = []
        self.next_id = 1000

    async def send_file(self, entity, file, **kwargs):
        self.calls.append(("file", entity, file, kwargs))
        self.next_id += 1
        return SimpleNamespace(id=self.next_id)

    async def send_message(self, entity, message, **kwargs):
        self.calls.append(("message", entity, message, kwargs))
        self.next_id += 1
        return SimpleNamespace(id=self.next_id)


class ReplyForwardingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        userbot.DEST_CHANNEL = "@test_destination"
        userbot.SOURCE_CHAT_ID = 123
        userbot.SENT_POSTS.clear()
        userbot.POST_MAP.clear()
        userbot.LAST_SOURCE_ID = 0
        userbot.PROCESS_LOCK = asyncio.Lock()

    async def test_reply_posts_and_albums_are_forwarded(self):
        client = FakeClient()
        userbot.POST_MAP[userbot.build_unique_id(123, 10)] = 900

        voice_reply = SimpleNamespace(
            id=11,
            media=object(),
            message="Nexia 2 sotildi. Tabriklaymiz.",
            reply_to=SimpleNamespace(reply_to_msg_id=10),
        )
        standalone_reply = SimpleNamespace(
            id=12,
            media=None,
            message="Kobalt sotildi.",
            reply_to=SimpleNamespace(reply_to_msg_id=999),
        )
        album_reply = [
            SimpleNamespace(
                id=13,
                media=object(),
                message="Album reply",
                reply_to=SimpleNamespace(reply_to_msg_id=10),
            ),
            SimpleNamespace(
                id=14,
                media=object(),
                message="",
                reply_to=SimpleNamespace(reply_to_msg_id=10),
            ),
        ]

        with patch.object(userbot, "save_state"), patch.object(
            userbot, "save_many_to_history"
        ):
            self.assertTrue(
                await userbot.process_single_message(client, 123, voice_reply)
            )
            self.assertEqual(client.calls[-1][0], "file")
            self.assertEqual(client.calls[-1][3]["reply_to"], 900)
            self.assertTrue(
                client.calls[-1][3]["caption"].startswith("Nexia 2 sotildi")
            )

            self.assertTrue(
                await userbot.process_single_message(client, 123, standalone_reply)
            )
            self.assertEqual(client.calls[-1][0], "message")
            self.assertIsNone(client.calls[-1][3]["reply_to"])

            self.assertTrue(
                await userbot.process_album_messages(client, 123, album_reply)
            )
            self.assertEqual(client.calls[-1][0], "file")
            self.assertEqual(client.calls[-1][3]["reply_to"], 900)


if __name__ == "__main__":
    unittest.main()
