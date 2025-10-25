# web_gen/db_queries.py
import sqlite3
from datetime import datetime
import math  # Для расчёта количества страниц при пагинации
# --- ИМПОРТ НОВОЙ ФУНКЦИИ ИЗ database.py ---
from database import get_file_size_by_path
# --- КОНЕЦ ИМПОРТА ---

def get_db_stats(conn):
    """Получает статистику из БД."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM topics")
    total_topics = cursor.fetchone()[0]
    cursor.execute("""
        SELECT t.title, COUNT(m.id) as msg_count
        FROM topics t
        LEFT JOIN messages m ON t.telegram_id = m.topic_id
        GROUP BY t.id
        ORDER BY msg_count DESC
        LIMIT 1
    """)
    most_active_topic_row = cursor.fetchone()
    most_active_topic = most_active_topic_row[0] if most_active_topic_row else "Нет тем"
    return total_messages, total_topics, most_active_topic

def get_topics(conn, ranking_method="by_messages", config=None):
    """Получает список тем из БД."""
    cursor = conn.cursor()
    if ranking_method == "by_messages":
        cursor.execute("""
            SELECT t.telegram_id, t.title, t.icon_emoji, COUNT(m.id) as msg_count
            FROM topics t
            LEFT JOIN messages m ON t.telegram_id = m.topic_id
            GROUP BY t.id
            ORDER BY msg_count DESC
        """)
    elif ranking_method == "alphabetical":
        cursor.execute("""
            SELECT t.telegram_id, t.title, t.icon_emoji, COUNT(m.id) as msg_count
            FROM topics t
            LEFT JOIN messages m ON t.telegram_id = m.topic_id
            GROUP BY t.id
            ORDER BY t.title ASC
        """)
    else:
        print(f"[WARNING] Метод сортировки '{ranking_method}' не реализован, используется 'by_messages'")
        return get_topics(conn, "by_messages", config)
    rows = cursor.fetchall()
    topics = []
    config_icon_map = {}
    if config and 'topic_icons' in config:
        config_icon_map = config['topic_icons']
    for row in rows:
        topic_telegram_id = row[0]
        topic_db_icon = row[2]
        final_icon = topic_db_icon
        if final_icon is None:
            final_icon = config_icon_map.get(topic_telegram_id)
        topics.append({
            'id': topic_telegram_id,
            'title': row[1],
            'icon_emoji': final_icon,
            'message_count': row[3]
        })
    print(f"[DEBUG] Найдено тем: {len(topics)}")
    return topics

def get_topic_info(conn, topic_telegram_id, config=None):
    """Получает основную информацию о теме."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT title, icon_emoji, COUNT(m.id) as total_messages,
               MIN(m.timestamp) as first_message_time,
               MAX(m.timestamp) as last_message_time
        FROM topics t
        LEFT JOIN messages m ON t.telegram_id = m.topic_id
        WHERE t.telegram_id = ?
        GROUP BY t.id
    """, (topic_telegram_id,))
    row = cursor.fetchone()
    if row:
        topic_db_icon = row[1]
        final_icon = topic_db_icon
        if final_icon is None and config and 'topic_icons' in config:
            final_icon = config['topic_icons'].get(topic_telegram_id)
        return {
            'id': topic_telegram_id,  # ←←← КЛЮЧЕВОЕ: теперь есть 'id'
            'title': row[0],
            'icon_emoji': final_icon,
            'total_messages': row[2] or 0,
            'first_message_time': datetime.fromisoformat(row[3]).strftime('%Y-%m-%d %H:%M:%S') if row[3] else "N/A",
            'last_message_time': datetime.fromisoformat(row[4]).strftime('%Y-%m-%d %H:%M:%S') if row[4] else "N/A"
        }
    print(f"[DEBUG] Информация о теме {topic_telegram_id} не найдена в БД")
    return None

# --- ИЗМЕНЕНИЕ: get_messages_for_topic теперь принимает config ---
def get_messages_for_topic(conn, topic_telegram_id, order="newest_first", page=1, per_page=50, config=None):
    """Получает сообщения для конкретной темы с пагинацией и сортировкой."""
    cursor = conn.cursor()
    offset = (page - 1) * per_page
    order_sql = "DESC" if order == "newest_first" else "ASC"
    query = f"""
        SELECT m.telegram_id, m.text, m.timestamp, m.media_path, m.media_type, m.file_extension, u.username, u.first_name, u.last_name, u.avatar_path
        FROM messages m
        JOIN users u ON m.user_id = u.telegram_id
        WHERE m.topic_id = ?
        ORDER BY m.timestamp {order_sql}
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, (topic_telegram_id, per_page, offset))
    rows = cursor.fetchall()
    messages = []
    # --- ПРОВЕРКА РЕЖИМА АНОНИМИЗАЦИИ ---
    privacy_config = config.get('ui', {}).get('privacy', {})
    is_anonymous_mode = privacy_config.get('mode', 'normal') == 'anonymous'
    anonymous_nickname = privacy_config.get('anonymous_nickname', 'Аноним')
    # --- КОНЕЦ ПРОВЕРКИ ---

    for row in rows:
        message_dict = {
            'id': row[0],
            'text': row[1],
            'timestamp': datetime.fromisoformat(row[2]).strftime('%Y-%m-%d %H:%M:%S'),
            'media_path': row[3],
            'media_type': row[4],
            'file_extension': row[5],
            'author_username': row[6],
            'author_first_name': row[7],
            'author_last_name': row[8],
            'author_avatar_path': row[9]
        }
        # --- АНОНИМИЗАЦИЯ ---
        if is_anonymous_mode:
            message_dict['author_username'] = None # или anonymous_nickname, если хочешь показывать его как юзернейм
            message_dict['author_first_name'] = anonymous_nickname
            message_dict['author_last_name'] = '' # или None
            # avatar_path можно оставить как есть, если хочешь, чтобы у анонимов была общая аватарка,
            # или установить на дефолтную в config и обработать в шаблоне.
            # message_dict['author_avatar_path'] = None # или путь к дефолтной анонимной аватарке
        # --- КОНЕЦ АНОНИМИЗАЦИИ ---

        # --- ПОЛУЧЕНИЕ РАЗМЕРА ФАЙЛА ---
        if message_dict['media_path']:
            file_size_bytes = get_file_size_by_path(conn, message_dict['media_path'])
            message_dict['file_size_bytes'] = file_size_bytes
            # Функция human_readable_size определена в message_processor.py, но её можно перенести или импортировать
            # Пока что просто сохраним байты, преобразование в шаблоне будет
        else:
            message_dict['file_size_bytes'] = None
        # --- КОНЕЦ ПОЛУЧЕНИЯ РАЗМЕРА ---
        messages.append(message_dict)
    print(f"[DEBUG] Найдено сообщений для темы {topic_telegram_id}, страница {page}: {len(messages)}")
    return messages
# --- КОНЕЦ ИЗМЕНЕНИЯ ---

def get_total_message_pages_for_topic(conn, topic_telegram_id, per_page=50):
    """Получает общее количество страниц для сообщений в теме."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages WHERE topic_id = ?", (topic_telegram_id,))
    total_count = cursor.fetchone()[0]
    pages = math.ceil(total_count / per_page) if per_page > 0 else 0
    print(f"[DEBUG] Всего сообщений для темы {topic_telegram_id}: {total_count}, страниц при {per_page} на странице: {pages}")
    return pages
