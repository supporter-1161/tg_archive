"""Тесты синхронизации: поддельный Telegram, настоящие SyncLogic/database."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection, init_db  # noqa: E402
from client.sync_logic import SyncLogic  # noqa: E402
from client.message_processor import MessageProcessor  # noqa: E402


class FakeReply:
    def __init__(self, reply_to_msg_id):
        self.reply_to_msg_id = reply_to_msg_id


class FakeMsg:
    def __init__(self, msg_id, topic_id, sender_id=1, text='msg', action=None, reply_to=None):
        self.id = msg_id
        self.sender_id = sender_id
        self.text = text
        self.action = action
        self.date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.media = None
        self.poll = None
        self.sender = None
        self.file = None
        self.reply_to = FakeReply(reply_to) if reply_to is not None else None


class FakeAPI:
    """Эмулирует семантику Telethon: reverse=True идёт от старых к новым."""

    def __init__(self, messages, topics=None, service_ids=(), replies=None):
        self.messages = sorted(messages, key=lambda m: m.id)
        self.topics = topics or [{'telegram_id': 100, 'title': 'Топик', 'icon_emoji': None, 'is_closed': False}]
        self.service_ids = set(service_ids)
        self.replies = replies or {}
        self.page_calls = 0
        self.user_calls = 0

    async def get_topics(self):
        return list(self.topics)

    async def get_messages(self, topic_id=None, offset_id=0, limit=100, reverse=False):
        self.page_calls += 1
        ids = [m.id for m in self.messages]
        if reverse:
            candidates = [m for m in self.messages if m.id > offset_id][:limit]
        else:
            if offset_id:
                candidates = [m for m in self.messages if m.id < offset_id]
            else:
                candidates = list(self.messages)
            candidates = candidates[-limit:][::-1]
        out = []
        for m in candidates:
            if m.id in self.service_ids:
                m.action = 'service'
            if m.id in self.replies:
                m.reply_to = FakeReply(self.replies[m.id])
            out.append(m)
        return out

    async def get_user_info(self, user_id):
        self.user_calls += 1
        return {'telegram_id': user_id, 'username': f'u{user_id}', 'first_name': 'User', 'last_name': ''}

    @staticmethod
    def user_to_dict(entity):
        return {
            'telegram_id': entity.id,
            'username': getattr(entity, 'username', None),
            'first_name': getattr(entity, 'first_name', None),
            'last_name': getattr(entity, 'last_name', None),
        }


class SyncTestCase(unittest.TestCase):
    topic_id = 100

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'test.db')
        self.media_dir = os.path.join(self.tmp.name, 'media')
        os.makedirs(self.media_dir, exist_ok=True)
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def make_sync(self, api):
        processor = MessageProcessor(api, self.db_path)
        return SyncLogic(api, processor, batch_size=100, sleep_range=(0, 0))

    def run_sync(self, api, direction='forward'):
        sync = self.make_sync(api)
        asyncio.run(sync.sync_topics_and_messages(
            self.db_path, self.media_dir, verbose=False, sync_direction=direction
        ))

    def rows(self):
        conn = get_db_connection(self.db_path)
        try:
            return conn.execute(
                'SELECT telegram_id, topic_id, reply_to_msg_id FROM messages ORDER BY telegram_id'
            ).fetchall()
        finally:
            conn.close()

    def last_id(self):
        conn = get_db_connection(self.db_path)
        try:
            return conn.execute(
                'SELECT last_message_id FROM topics WHERE telegram_id = ?', (self.topic_id,)
            ).fetchone()[0]
        finally:
            conn.close()

    # --- тесты -------------------------------------------------------------

    def test_forward_fills_history_then_stops(self):
        api = FakeAPI([FakeMsg(i, self.topic_id) for i in range(1, 251)])
        self.run_sync(api, 'forward')
        self.assertEqual(len(self.rows()), 250)
        self.assertEqual(self.last_id(), 250)

        api.page_calls = 0
        self.run_sync(api, 'forward')
        self.assertEqual(len(self.rows()), 250)
        self.assertEqual(api.page_calls, 1, 'повторный forward должен упираться в known id сразу')

    def test_forward_picks_only_new(self):
        api = FakeAPI([FakeMsg(i, self.topic_id) for i in range(1, 101)])
        self.run_sync(api, 'forward')
        api.messages += [FakeMsg(i, self.topic_id) for i in range(101, 121)]
        api.messages.sort(key=lambda m: m.id)
        self.run_sync(api, 'forward')
        self.assertEqual(len(self.rows()), 120)
        self.assertEqual(self.last_id(), 120)

    def test_forward_paginates_by_batch_not_by_one(self):
        api = FakeAPI([FakeMsg(i, self.topic_id) for i in range(1, 251)])
        self.run_sync(api, 'forward')
        # 100 + 100 + 50 → три запроса, а не 250
        self.assertEqual(api.page_calls, 3)

    def test_backward_fills_gaps(self):
        api = FakeAPI([FakeMsg(i, self.topic_id) for i in range(1, 251)])
        self.run_sync(api, 'forward')
        conn = get_db_connection(self.db_path)
        conn.execute('DELETE FROM messages WHERE telegram_id % 7 = 0')
        conn.commit()
        conn.close()
        before = len(self.rows())
        self.assertLess(before, 250)

        api.page_calls = 0
        self.run_sync(api, 'backward')
        self.assertEqual(len(self.rows()), 250)
        # полный проход: 3 страницы по 100/100/50
        self.assertEqual(api.page_calls, 3)

    def test_reply_to_is_not_topic_id(self):
        api = FakeAPI(
            [FakeMsg(i, self.topic_id) for i in range(10, 13)],
            replies={11: self.topic_id, 12: 10},
        )
        self.run_sync(api, 'forward')
        rows = {r['telegram_id']: r['reply_to_msg_id'] for r in self.rows()}
        self.assertIsNone(rows[10])
        self.assertIsNone(rows[11], 'reply_to_msg_id == topic_id — это привязка к теме, не ответ')
        self.assertEqual(rows[12], 10)

    def test_service_messages_skipped(self):
        api = FakeAPI([FakeMsg(i, self.topic_id) for i in range(1, 6)], service_ids={3})
        self.run_sync(api, 'forward')
        self.assertEqual([r['telegram_id'] for r in self.rows()], [1, 2, 4, 5])

    def test_user_fetched_once_per_sender(self):
        api = FakeAPI([FakeMsg(i, self.topic_id, sender_id=42) for i in range(1, 6)])
        self.run_sync(api, 'forward')
        self.assertEqual(api.user_calls, 1)
        conn = get_db_connection(self.db_path)
        users = conn.execute('SELECT COUNT(*) FROM users WHERE telegram_id = 42').fetchone()[0]
        conn.close()
        self.assertEqual(users, 1)

    def test_topic_id_zero_when_no_topic(self):
        api = FakeAPI([FakeMsg(1, 0)], topics=[{'telegram_id': 0, 'title': 'General', 'icon_emoji': None, 'is_closed': False}])
        sync = self.make_sync(api)
        asyncio.run(sync.sync_topics_and_messages(self.db_path, self.media_dir, sync_direction='forward'))
        self.assertEqual(self.rows()[0]['topic_id'], 0)


if __name__ == '__main__':
    unittest.main()
