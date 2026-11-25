"""Тесты миграции схемы v1 -> v2 -> v3."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection, init_db, save_message  # noqa: E402

OLD_SCHEMA = """
    CREATE TABLE topics (
        id INTEGER PRIMARY KEY,
        telegram_id INTEGER UNIQUE NOT NULL,
        title TEXT NOT NULL,
        icon_emoji TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_closed BOOLEAN DEFAULT FALSE,
        last_message_id INTEGER
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY,
        telegram_id INTEGER NOT NULL,
        topic_id INTEGER REFERENCES topics(id),
        user_id INTEGER NOT NULL,
        text TEXT,
        timestamp TIMESTAMP NOT NULL,
        reply_to INTEGER REFERENCES messages(id),
        media_path TEXT,
        media_type TEXT CHECK(media_type IN ('photo', 'video', 'document', 'audio')),
        poll_data TEXT,
        deleted BOOLEAN DEFAULT FALSE,
        file_extension TEXT,
        UNIQUE(telegram_id, topic_id)
    );
"""

V2_SCHEMA = """
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY,
        telegram_id INTEGER NOT NULL,
        topic_id INTEGER NOT NULL DEFAULT 0,
        user_id INTEGER NOT NULL,
        text TEXT,
        timestamp TIMESTAMP NOT NULL,
        reply_to_msg_id INTEGER,
        media_path TEXT,
        media_type TEXT CHECK(media_type IN ('photo', 'video', 'document', 'audio')),
        poll_data TEXT,
        deleted BOOLEAN DEFAULT FALSE,
        file_extension TEXT,
        UNIQUE(telegram_id, topic_id)
    );
"""


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'old.db')

    def tearDown(self):
        self.tmp.cleanup()

    def make_v1(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(OLD_SCHEMA)
        conn.execute("INSERT INTO topics (telegram_id, title) VALUES (1143, 'Тема')")
        conn.execute("""INSERT INTO messages
            (telegram_id, topic_id, user_id, text, timestamp, reply_to, media_path, media_type, file_extension)
            VALUES (2402, 1143, 7, 'текст', '2025-10-25T10:12:15+00:00', 1143,
                    'media/topics/1143/a.jpg', 'photo', 'jpg')""")
        conn.execute("""INSERT INTO messages
            (telegram_id, topic_id, user_id, text, timestamp, reply_to)
            VALUES (2403, NULL, 7, 'без темы', '2025-10-25T10:13:15+00:00', NULL)""")
        conn.commit()
        conn.close()

    def test_migrates_reply_to_and_null_topic(self):
        self.make_v1()
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
        self.assertIn('reply_to_msg_id', columns)
        self.assertIn('media_skipped_size', columns)
        self.assertNotIn('reply_to', columns)

        rows = list(conn.execute(
            'SELECT telegram_id, topic_id, reply_to_msg_id, media_path FROM messages ORDER BY telegram_id'
        ))
        self.assertEqual(rows[0][1], 1143)
        self.assertIsNone(rows[0][2], 'старый reply_to (id топика) не должен стать ответом')
        self.assertEqual(rows[0][3], 'media/topics/1143/a.jpg')
        self.assertEqual(rows[1][1], 0, 'NULL-топик приводится к 0')
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
        conn.close()
        self.assertTrue(os.path.exists(self.db_path + '.pre-v2.bak'))

    def test_v2_to_v4_adds_columns(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(V2_SCHEMA)
        conn.execute("PRAGMA user_version = 2")
        conn.execute("""INSERT INTO messages (telegram_id, topic_id, user_id, text, timestamp)
                        VALUES (1, 0, 1, 'x', '2025-01-01T00:00:00+00:00')""")
        conn.commit()
        conn.close()

        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
        self.assertIn('media_skipped_size', columns)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)
        conn.close()

    def test_migration_is_idempotent(self):
        self.make_v1()
        init_db(self.db_path)
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)
        self.assertEqual(version, 4)

    def test_duplicates_blocked_with_zero_topic(self):
        self.make_v1()
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""INSERT INTO messages (telegram_id, topic_id, user_id, text, timestamp)
                        VALUES (2403, 0, 7, 'без темы', '2025-10-25T10:13:15+00:00')
                        ON CONFLICT(telegram_id, topic_id) DO UPDATE SET text='обновлено'""")
        conn.commit()
        count = conn.execute('SELECT COUNT(*) FROM messages WHERE telegram_id=2403').fetchone()[0]
        text = conn.execute('SELECT text FROM messages WHERE telegram_id=2403').fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)
        self.assertEqual(text, 'обновлено')

    def test_save_message_stores_skipped_size(self):
        self.make_v1()
        init_db(self.db_path)
        conn = get_db_connection(self.db_path)
        save_message(conn, {
            'telegram_id': 5000, 'topic_id': 1143, 'user_id': 1, 'text': 'архив',
            'timestamp': '2025-01-01T00:00:00+00:00', 'reply_to_msg_id': None,
            'media_type': 'document', 'media_path': None,
            'media_skipped_size': 4 * 1024 ** 3, 'file_extension': '7z',
        })
        row = conn.execute(
            "SELECT media_skipped_size, media_type, file_extension FROM messages WHERE telegram_id=5000"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 4 * 1024 ** 3)
        self.assertEqual(row[1], 'document')
        self.assertEqual(row[2], '7z')


if __name__ == '__main__':
    unittest.main()
