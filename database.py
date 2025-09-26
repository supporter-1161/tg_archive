import sqlite3
import os
from typing import Optional, Dict, Any

def init_db(db_path: str):
    """Создаёт таблицы в БД, если их ещё нет."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE NOT NULL,
            title TEXT NOT NULL,
            icon_emoji TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_closed BOOLEAN DEFAULT FALSE,
            last_message_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER NOT NULL,
            topic_id INTEGER REFERENCES topics(id),
            user_id INTEGER NOT NULL,
            text TEXT,
            timestamp TIMESTAMP NOT NULL,
            reply_to INTEGER REFERENCES messages(id),
            media_path TEXT,
            media_type TEXT CHECK(media_type IN ('photo', 'video', 'document', 'audio')),
            poll_data TEXT, -- JSON stored as TEXT
            deleted BOOLEAN DEFAULT FALSE,
            UNIQUE(telegram_id, topic_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            avatar_path TEXT,
            last_updated TIMESTAMP
        )
    """)

    # Индексы
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_reply ON messages(reply_to)")

    conn.commit()
    conn.close()


def get_db_connection(db_path: str):
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Для доступа по именам колонок
    return conn


def save_topic(conn, topic_data: Dict[str, Any]):
    """Сохраняет или обновляет тему."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO topics (telegram_id, title, icon_emoji, is_closed, last_message_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            title=excluded.title,
            icon_emoji=excluded.icon_emoji,
            is_closed=excluded.is_closed
    """, (
        topic_data['telegram_id'],
        topic_data['title'],
        topic_data.get('icon_emoji'),
        topic_data.get('is_closed', False),
        topic_data.get('last_message_id')
    ))
    conn.commit()


def get_last_message_id(conn, topic_id: int) -> Optional[int]:
    """Возвращает последний сохранённый message_id для темы."""
    cursor = conn.cursor()
    cursor.execute("SELECT last_message_id FROM topics WHERE telegram_id = ?", (topic_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def update_last_message_id(conn, topic_id: int, message_id: int):
    """Обновляет last_message_id для темы."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE topics SET last_message_id = ? WHERE telegram_id = ?
    """, (message_id, topic_id))
    conn.commit()


def save_user(conn, user_data: Dict[str, Any]):
    """Сохраняет или обновляет пользователя."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (telegram_id, username, first_name, last_name, avatar_path, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            avatar_path=excluded.avatar_path,
            last_updated=excluded.last_updated
    """, (
        user_data['telegram_id'],
        user_data.get('username'),
        user_data.get('first_name'),
        user_data.get('last_name'),
        user_data.get('avatar_path'),
        user_data.get('last_updated')
    ))
    conn.commit()


def save_message(conn, msg_data: Dict[str, Any]):
    """Сохраняет сообщение."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO messages (
            telegram_id, topic_id, user_id, text, timestamp,
            reply_to, media_path, media_type, poll_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        msg_data['telegram_id'],
        msg_data.get('topic_id'),
        msg_data['user_id'],
        msg_data.get('text'),
        msg_data['timestamp'],
        msg_data.get('reply_to'),
        msg_data.get('media_path'),
        msg_data.get('media_type'),
        msg_data.get('poll_data')  # JSON -> str
    ))
    conn.commit()
