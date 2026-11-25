# database.py
"""Схема и доступ к SQLite.

Схема версионируется через ``PRAGMA user_version``:

* v1 — исходная схема (reply_to ссылался на messages(id), topic_id допускал NULL);
* v2 — ``reply_to`` заменён на ``reply_to_msg_id`` (id сообщения в Telegram),
  ``topic_id`` объявлен NOT NULL DEFAULT 0, чтобы UNIQUE(telegram_id, topic_id)
  реально работал (в SQLite NULL-ы считаются различными).
"""
import os
import shutil
import sqlite3
from typing import Optional, Dict, Any, Set

SCHEMA_VERSION = 4

MESSAGES_DDL = """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        telegram_id INTEGER NOT NULL,
        topic_id INTEGER NOT NULL DEFAULT 0,  -- telegram id топика, 0 = без топика
        user_id INTEGER NOT NULL,
        text TEXT,
        timestamp TIMESTAMP NOT NULL,
        reply_to_msg_id INTEGER,              -- telegram id сообщения, на которое ответ
        grouped_id INTEGER,                   -- id альбома (несколько фото одним постом)
        media_path TEXT,
        media_type TEXT CHECK(media_type IN ('photo', 'video', 'document', 'audio')),
        media_skipped_size INTEGER,           -- размер вложения, не скачанного из-за лимита
        poll_data TEXT,                       -- JSON stored as TEXT
        deleted BOOLEAN DEFAULT FALSE,
        file_extension TEXT,
        UNIQUE(telegram_id, topic_id)
    )
"""


def _create_schema(conn: sqlite3.Connection):
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
    cursor.execute(MESSAGES_DDL)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY,
            telegram_media_id INTEGER NOT NULL,
            access_hash INTEGER NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            file_size INTEGER,
            UNIQUE(telegram_media_id, access_hash)
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generation_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            run_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    _create_indexes(conn)
    conn.commit()


def _create_indexes(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_topic_tg ON messages(topic_id, telegram_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_files_telegram_ids ON media_files(telegram_media_id, access_hash, file_size)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_files_path ON media_files(file_path)")


def _table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection, db_path: str):
    """Приводит существующую базу к актуальной версии схемы."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    columns = _table_columns(conn, "messages")

    if version < 2 and "reply_to" in columns:
        backup_path = f"{db_path}.pre-v2.bak"
        if os.path.exists(db_path) and not os.path.exists(backup_path):
            shutil.copy2(db_path, backup_path)
            print(f"[.] Бэкап схемы v1: {backup_path}")

        conn.commit()
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE messages RENAME TO messages_legacy")
        cursor.execute(MESSAGES_DDL.replace("IF NOT EXISTS ", ""))
        # reply_to хранил id топика (в форуме так ведёт себя reply_to_msg_id), а не
        # id сообщения — переносить его в reply_to_msg_id нельзя, теряем как мусор.
        cursor.execute("""
            INSERT INTO messages (
                telegram_id, topic_id, user_id, text, timestamp,
                reply_to_msg_id, media_path, media_type, poll_data, deleted, file_extension
            )
            SELECT telegram_id, COALESCE(topic_id, 0), user_id, text, timestamp,
                   NULL, media_path, media_type, poll_data, COALESCE(deleted, 0), file_extension
            FROM messages_legacy
        """)
        cursor.execute("DROP TABLE messages_legacy")
        _create_indexes(conn)
        conn.commit()
        print("[+] Схема БД обновлена до v2 (reply_to_msg_id, topic_id NOT NULL)")

    columns = _table_columns(conn, "messages")
    if 'media_skipped_size' not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN media_skipped_size INTEGER")
        conn.commit()
        print("[+] Схема БД обновлена до v3 (media_skipped_size)")

    columns = _table_columns(conn, "messages")
    if 'grouped_id' not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN grouped_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_grouped ON messages(topic_id, grouped_id)")
        conn.commit()
        print("[+] Схема БД обновлена до v4 (grouped_id)")

    if version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def init_db(db_path: str):
    """Создаёт/обновляет схему БД."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    try:
        _create_schema(conn)
        _migrate(conn, db_path)
    finally:
        conn.close()


def get_db_connection(db_path: str):
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def save_topic(conn, topic_data: Dict[str, Any]):
    """Сохраняет или обновляет тему."""
    conn.execute("""
        INSERT INTO topics (telegram_id, title, icon_emoji, is_closed, last_message_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            title=excluded.title,
            icon_emoji=COALESCE(excluded.icon_emoji, topics.icon_emoji),
            is_closed=excluded.is_closed
    """, (
        topic_data['telegram_id'],
        topic_data['title'],
        topic_data.get('icon_emoji'),
        topic_data.get('is_closed', False),
        topic_data.get('last_message_id')
    ))


def get_last_message_id(conn, topic_id: int) -> Optional[int]:
    """Возвращает последний сохранённый message_id для темы."""
    row = conn.execute(
        "SELECT last_message_id FROM topics WHERE telegram_id = ?", (topic_id,)
    ).fetchone()
    return row[0] if row else None


def update_last_message_id(conn, topic_id: int, message_id: int, commit: bool = True):
    """Обновляет last_message_id для темы (только вверх)."""
    conn.execute("""
        UPDATE topics SET last_message_id = ?
        WHERE telegram_id = ? AND (last_message_id IS NULL OR last_message_id < ?)
    """, (message_id, topic_id, message_id))
    if commit:
        conn.commit()


def get_min_message_id(conn, topic_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT MIN(telegram_id) FROM messages WHERE topic_id = ?", (topic_id,)
    ).fetchone()
    return row[0] if row else None


def get_known_message_ids(conn, topic_id: int, id_from: int, id_to: int) -> Set[int]:
    """Возвращает уже сохранённые telegram_id темы в диапазоне (для skip)."""
    rows = conn.execute(
        "SELECT telegram_id FROM messages WHERE topic_id = ? AND telegram_id BETWEEN ? AND ?",
        (topic_id, id_from, id_to)
    )
    return {row[0] for row in rows}


def get_user(conn, telegram_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()


def save_user(conn, user_data: Dict[str, Any], commit: bool = True):
    """Сохраняет или обновляет пользователя.

    Пустые значения не затирают уже известные: аватар и имя, полученные ранее,
    должны переживать повторные синхронизации.
    """
    conn.execute("""
        INSERT INTO users (telegram_id, username, first_name, last_name, avatar_path, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=COALESCE(excluded.username, users.username),
            first_name=COALESCE(excluded.first_name, users.first_name),
            last_name=COALESCE(excluded.last_name, users.last_name),
            avatar_path=COALESCE(excluded.avatar_path, users.avatar_path),
            last_updated=excluded.last_updated
    """, (
        user_data['telegram_id'],
        user_data.get('username'),
        user_data.get('first_name'),
        user_data.get('last_name'),
        user_data.get('avatar_path'),
        user_data.get('last_updated')
    ))
    if commit:
        conn.commit()


def save_message(conn, msg_data: Dict[str, Any], commit: bool = True):
    """Сохраняет сообщение или обновляет, если уже существует."""
    conn.execute("""
        INSERT INTO messages (
            telegram_id, topic_id, user_id, text, timestamp,
            reply_to_msg_id, grouped_id, media_path, media_type, media_skipped_size,
            poll_data, file_extension
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id, topic_id) DO UPDATE SET
            user_id = excluded.user_id,
            text = COALESCE(excluded.text, messages.text),
            timestamp = excluded.timestamp,
            reply_to_msg_id = COALESCE(excluded.reply_to_msg_id, messages.reply_to_msg_id),
            grouped_id = COALESCE(excluded.grouped_id, messages.grouped_id),
            media_path = COALESCE(excluded.media_path, messages.media_path),
            media_type = COALESCE(excluded.media_type, messages.media_type),
            media_skipped_size = COALESCE(excluded.media_skipped_size, messages.media_skipped_size),
            poll_data = COALESCE(excluded.poll_data, messages.poll_data),
            file_extension = COALESCE(excluded.file_extension, messages.file_extension)
    """, (
        msg_data['telegram_id'],
        msg_data.get('topic_id') or 0,
        msg_data['user_id'],
        msg_data.get('text'),
        msg_data['timestamp'],
        msg_data.get('reply_to_msg_id'),
        msg_data.get('grouped_id'),
        msg_data.get('media_path'),
        msg_data.get('media_type'),
        msg_data.get('media_skipped_size'),
        msg_data.get('poll_data'),  # JSON -> str
        msg_data.get('file_extension')
    ))
    if commit:
        conn.commit()


def get_file_path_by_media_info(conn, media_id: int, access_hash: int) -> Optional[str]:
    """Возвращает путь к файлу, если он уже был скачан."""
    row = conn.execute(
        "SELECT file_path FROM media_files WHERE telegram_media_id = ? AND access_hash = ?",
        (media_id, access_hash)
    ).fetchone()
    return row[0] if row else None


def save_media_file_info(conn, media_id: int, access_hash: int, file_path: str,
                         file_size: Optional[int] = None, commit: bool = True):
    """Сохраняет информацию о скачанном файле."""
    conn.execute("""
        INSERT INTO media_files (telegram_media_id, access_hash, file_path, file_size)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_media_id, access_hash) DO UPDATE SET
            file_path=excluded.file_path,
            file_size=COALESCE(excluded.file_size, media_files.file_size)
    """, (media_id, access_hash, file_path, file_size))
    if commit:
        conn.commit()


def get_file_size_by_path(conn, file_path: str) -> Optional[int]:
    """Возвращает размер файла в байтах по его пути."""
    row = conn.execute(
        "SELECT file_size FROM media_files WHERE file_path = ?", (file_path,)
    ).fetchone()
    return row[0] if row else None


def get_generation_run_count(conn) -> int:
    """Получает текущий счётчик запусков генерации."""
    row = conn.execute("SELECT run_count FROM generation_stats WHERE id = 1").fetchone()
    if row:
        return row[0]
    conn.execute("INSERT INTO generation_stats (id, run_count) VALUES (1, 0)")
    conn.commit()
    return 0


def increment_generation_run_count(conn) -> int:
    """Увеличивает счётчик запусков генерации на 1 и возвращает новое значение."""
    cursor = conn.cursor()
    cursor.execute("UPDATE generation_stats SET run_count = run_count + 1 WHERE id = 1")
    if cursor.rowcount == 0:
        conn.execute("INSERT INTO generation_stats (id, run_count) VALUES (1, 1)")
        conn.commit()
        return 1
    new_count = conn.execute("SELECT run_count FROM generation_stats WHERE id = 1").fetchone()[0]
    conn.commit()
    return new_count
