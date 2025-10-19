# web_generator.py
import os
import shutil
from jinja2 import Environment, FileSystemLoader
import sqlite3
from datetime import datetime
import yaml
import math # Для расчёта количества страниц при пагинации
# --- Функции для работы с БД ---
def get_db_stats(conn):
    """Получает статистику из БД."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM topics")
    total_topics = cursor.fetchone()[0]
    # Пример запроса для самой активной темы (по количеству сообщений)
    # Зависит от сортировки, которую мы реализуем в генераторе
    # Пока просто возвращаем общие числа
    cursor.execute("""
        SELECT t.title, COUNT(m.id) as msg_count
        FROM topics t
        LEFT JOIN messages m ON t.telegram_id = m.topic_id -- Исправлено: t.telegram_id = m.topic_id
        GROUP BY t.id
        ORDER BY msg_count DESC
        LIMIT 1
    """)
    most_active_topic_row = cursor.fetchone()
    most_active_topic = most_active_topic_row[0] if most_active_topic_row else "Нет тем"
    return total_messages, total_topics, most_active_topic

# --- ИЗМЕНЕНИЕ get_topics (добавлен параметр config) ---
def get_topics(conn, ranking_method="by_messages", config=None): # <-- Добавим config как аргумент
    """Получает список тем из БД."""
    cursor = conn.cursor()
    if ranking_method == "by_messages":
        # Сортировка по количеству сообщений (по убыванию)
        cursor.execute("""
            SELECT t.telegram_id, t.title, t.icon_emoji, COUNT(m.id) as msg_count
            FROM topics t
            LEFT JOIN messages m ON t.telegram_id = m.topic_id -- Исправлено: t.telegram_id = m.topic_id
            GROUP BY t.id
            ORDER BY msg_count DESC
        """)
    elif ranking_method == "alphabetical":
        # Сортировка по названию
        cursor.execute("""
            SELECT t.telegram_id, t.title, t.icon_emoji, COUNT(m.id) as msg_count
            FROM topics t
            LEFT JOIN messages m ON t.telegram_id = m.topic_id -- Исправлено: t.telegram_id = m.topic_id
            GROUP BY t.id
            ORDER BY t.title ASC
        """)
    else: # Заглушка для "manual" или других
        # Пока тоже по количеству сообщений
        print(f"[WARNING] Метод сортировки '{ranking_method}' не реализован, используется 'by_messages'")
        return get_topics(conn, "by_messages", config) # <-- Передаём config и дальше
    rows = cursor.fetchall()
    topics = []
    # --- ИЗМЕНЕНИЕ: Извлекаем маппинг из конфига ---
    config_icon_map = {}
    if config and 'topic_icons' in config:
        config_icon_map = config['topic_icons'] # Ожидаем словарь вида { telegram_id: emoji }
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---
    for row in rows:
        topic_telegram_id = row[0]
        topic_db_icon = row[2] # icon_emoji из БД
        # --- ИЗМЕНЕНИЕ: Проверяем БД, затем конфиг ---
        final_icon = topic_db_icon
        if final_icon is None:
            # Если в БД None, ищем в конфиге
            final_icon = config_icon_map.get(topic_telegram_id)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        topics.append({
            'id': topic_telegram_id, # Это telegram_id темы
            'title': row[1],
            'icon_emoji': final_icon, # <-- Используем final_icon
            'message_count': row[3] # Добавим счётчик для отображения в боковом меню
        })
    print(f"[DEBUG] Найдено тем: {len(topics)}") # Отладка
    return topics
# --- КОНЕЦ ИЗМЕНЕНИЯ get_topics ---

# --- ИЗМЕНЕНИЕ get_topic_info (добавлен параметр config) ---
def get_topic_info(conn, topic_telegram_id, config=None): # <-- Добавим config как аргумент
    """Получает основную информацию о теме."""
    cursor = conn.cursor()
    # Используем topic_telegram_id напрямую в WHERE
    cursor.execute("""
        SELECT title, icon_emoji, COUNT(m.id) as total_messages,
               MIN(m.timestamp) as first_message_time,
               MAX(m.timestamp) as last_message_time
        FROM topics t
        LEFT JOIN messages m ON t.telegram_id = m.topic_id -- Исправлено: t.telegram_id = m.topic_id
        WHERE t.telegram_id = ?
        GROUP BY t.id
    """, (topic_telegram_id,)) # topic_telegram_id передаётся как есть
    row = cursor.fetchone()
    if row:
        topic_db_icon = row[1] # icon_emoji из БД
        # --- ИЗМЕНЕНИЕ: Проверяем БД, затем конфиг ---
        final_icon = topic_db_icon
        if final_icon is None and config and 'topic_icons' in config:
            # Если в БД None, ищем в конфиге
            final_icon = config['topic_icons'].get(topic_telegram_id)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        return {
            'title': row[0],
            'icon_emoji': final_icon, # <-- Используем final_icon
            'total_messages': row[2] or 0,
            'first_message_time': datetime.fromisoformat(row[3]).strftime('%Y-%m-%d %H:%M:%S') if row[3] else "N/A",
            'last_message_time': datetime.fromisoformat(row[4]).strftime('%Y-%m-%d %H:%M:%S') if row[4] else "N/A"
        }
    print(f"[DEBUG] Информация о теме {topic_telegram_id} не найдена в БД") # Отладка
    return None
# --- КОНЕЦ ИЗМЕНЕНИЯ get_topic_info ---

def get_messages_for_topic(conn, topic_telegram_id, order="newest_first", page=1, per_page=50):
    """Получает сообщения для конкретной темы с пагинацией и сортировкой."""
    cursor = conn.cursor()
    offset = (page - 1) * per_page
    order_sql = "DESC" if order == "newest_first" else "ASC"
    # JOIN с таблицей users для получения имени автора
    # Используем topic_telegram_id напрямую в WHERE
    query = f"""
        SELECT m.telegram_id, m.text, m.timestamp, m.media_path, m.media_type, m.file_extension, u.username, u.first_name, u.last_name, u.avatar_path
        FROM messages m
        JOIN users u ON m.user_id = u.telegram_id
        WHERE m.topic_id = ?
        ORDER BY m.timestamp {order_sql}
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, (topic_telegram_id, per_page, offset)) # topic_telegram_id передаётся как есть
    rows = cursor.fetchall()
    messages = []
    for row in rows:
        messages.append({
            'id': row[0],
            'text': row[1],
            'timestamp': datetime.fromisoformat(row[2]).strftime('%Y-%m-%d %H:%M:%S'),
            'media_path': row[3],
            'media_type': row[4],
            'file_extension': row[5],
            'author_username': row[6],
            'author_first_name': row[7],
            'author_last_name': row[8],
            'author_avatar_path': row[9] # Путь к аватарке из БД
        })
    print(f"[DEBUG] Найдено сообщений для темы {topic_telegram_id}, страница {page}: {len(messages)}") # Отладка
    return messages

def get_total_message_pages_for_topic(conn, topic_telegram_id, per_page=50):
    """Получает общее количество страниц для сообщений в теме."""
    cursor = conn.cursor()
    # Используем topic_telegram_id напрямую в WHERE
    cursor.execute("""
        SELECT COUNT(*) FROM messages
        WHERE topic_id = ? -- Исправлено: используем topic_telegram_id напрямую
    """, (topic_telegram_id,)) # topic_telegram_id передаётся как есть
    total_count = cursor.fetchone()[0]
    pages = math.ceil(total_count / per_page) if per_page > 0 else 0
    print(f"[DEBUG] Всего сообщений для темы {topic_telegram_id}: {total_count}, страниц при {per_page} на странице: {pages}") # Отладка
    return pages

# --- Основной класс генератора ---
class WebGenerator:
    def __init__(self, config, db_path, output_dir): # Принимаем config напрямую
        self.config = config # Сохраняем конфиг
        self.db_path = db_path
        self.output_dir = output_dir
        # Настройка Jinja2
        self.jinja_env = Environment(
            loader=FileSystemLoader('templates'),
            autoescape=True
        )
        # Загрузка шаблонов
        self.index_template = self.jinja_env.get_template('index.html.j2')
        self.topic_template = self.jinja_env.get_template('topic.html.j2')

# --- Файл: web_generator.py ---
# Найди класс WebGenerator и замени его метод generate на этот:

    def generate(self):
        print(f"[*] Генерация веб-сайта в '{self.output_dir}'...")
        os.makedirs(self.output_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Для доступа по именам колонок

        # --- 1. Генерация главной страницы ---
        total_messages, total_topics, most_active_topic = get_db_stats(conn)
        # --- ИЗМЕНЕНИЕ: Передаём config в get_topics ---
        topics = get_topics(conn, self.config.get('ui', {}).get('topics_ranking', 'by_messages'), config=self.config)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        index_context = {
            'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
            'site_description': self.config.get('site', {}).get('description', ''),
            'footer_text': self.config.get('site', {}).get('footer_text', ''),
            'default_theme': self.config.get('ui', {}).get('theme', 'light'),
            'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
            'ticker_texts': self.config.get('ticker', {}).get('texts', []),
            'ticker_speed': self.config.get('ticker', {}).get('speed', 50),
            'ticker_delay': self.config.get('ticker', {}).get('delay', 5),
            'useful_links': self.config.get('useful_links', []),
            'total_messages': total_messages,
            'total_topics': total_topics,
            'most_active_topic': most_active_topic,
            'topics': topics,
            # --- ДОБАВЛЕНО ---
            'config': self.config # Передаём config в контекст шаблона index.html.j2
            # --- КОНЕЦ ДОБАВЛЕНИЯ ---
        }
        index_html_content = self.index_template.render(**index_context)
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(index_html_content)
        print(f"[+] Сгенерирована главная страница: index.html")

        # --- 2. Генерация страниц тем ---
        for topic in topics:
            topic_id = topic['id'] # Это telegram_id темы
            print(f"[DEBUG] Обработка темы: {topic_id} - {topic['title']}") # Отладка
            # --- ИЗМЕНЕНИЕ: Передаём config в get_topic_info ---
            topic_info = get_topic_info(conn, topic_id, config=self.config)
            # --- КОНЕЦ ИЗМЕНЕНИЯ ---
            if not topic_info:
                print(f"[WARNING] Информация о теме {topic_id} не найдена, пропуск.")
                continue # Переходим к следующей теме

            # --- Пагинация ---
            messages_per_page = self.config.get('ui', {}).get('messages_per_page', 50)
            total_pages = get_total_message_pages_for_topic(conn, topic_id, messages_per_page)
            order = self.config.get('ui', {}).get('messages_order', 'newest_first')

            if total_pages == 0:
                 print(f"[DEBUG] Для темы {topic_id} нет сообщений, пропускаем генерацию страниц темы.")
                 continue # Переходим к следующей теме, если нет сообщений

            for page_num in range(1, total_pages + 1):
                print(f"[DEBUG] Обработка страницы {page_num} для темы {topic_id}") # Отладка
                messages = get_messages_for_topic(conn, topic_id, order, page_num, messages_per_page)

                # Определяем имя файла для страницы темы
                # Если это первая страница, можно назвать её просто topic_{id}.html
                # или topic_{title}.html, но для простоты пока topic_{id}_page_{num}.html
                # или topic_{id}.html для первой страницы.
                if total_pages == 1:
                    filename = f"topic_{topic_id}.html"
                else:
                    filename = f"topic_{topic_id}_page_{page_num}.html"

                topic_context = {
                    'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
                    'site_description': self.config.get('site', {}).get('description', ''),
                    'footer_text': self.config.get('site', {}).get('footer_text', ''),
                    'default_theme': self.config.get('ui', {}).get('theme', 'light'),
                    'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
                    'ticker_texts': self.config.get('ticker', {}).get('texts', []),
                    'ticker_speed': self.config.get('ticker', {}).get('speed', 50),
                    'ticker_delay': self.config.get('ticker', {}).get('delay', 5),
                    'useful_links': self.config.get('useful_links', []),
                    'topics': topics, # Передаём список всех тем для бокового меню
                    'current_topic': topic_info,
                    'messages': messages,
                    'current_page': page_num,
                    'total_pages': total_pages,
                    'page_links': range(1, total_pages + 1), # Список номеров страниц для навигации
                    'messages_order': order,
                    'show_order_label': order == 'newest_first', # Показывать "от новых к старым" или "от старых к новым"
                    'config': self.config # Передаём config в контекст шаблона
                }
                topic_html_content = self.topic_template.render(**topic_context)
                output_file_path = os.path.join(self.output_dir, filename)
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(topic_html_content)
                print(f"[+] Сгенерирована страница темы: {filename} (Страница {page_num}/{total_pages})")
                print(f"      Путь: {output_file_path}") # Отладка: покажем путь

        conn.close()

        # --- 3. Копирование ресурсов (медиа, аватары, стили и т.д.) ---
        # Предположим, что стили и скрипты будут в папке 'static' в корне проекта
        static_src = 'static'
        static_dst = os.path.join(self.output_dir, 'static')
        if os.path.exists(static_src):
            if os.path.exists(static_dst):
                shutil.rmtree(static_dst)
            # --- ИСПРАВЛЕНО: используем static_src и static_dst ---
            shutil.copytree(static_src, static_dst)
            print(f"[+] Скопированы статические ресурсы из '{static_src}' в '{static_dst}'")

        # Копирование медиафайлов
        media_src = self.config.get('storage', {}).get('media_dir', 'media')
        media_dst = os.path.join(self.output_dir, 'media')
        if os.path.exists(media_src):
            if os.path.exists(media_dst):
                shutil.rmtree(media_dst)
            # --- ИСПРАВЛЕНО: используем media_src и media_dst ---
            shutil.copytree(media_src, media_dst)
            print(f"[+] Скопированы медиафайлы из '{media_src}' в '{media_dst}'")

        # Копирование аватаров (если используются)
        avatars_src = self.config.get('storage', {}).get('avatars_dir', 'avatars')
        avatars_dst = os.path.join(self.output_dir, 'avatars')
        if os.path.exists(avatars_src):
            if os.path.exists(avatars_dst):
                shutil.rmtree(avatars_dst)
            # --- ИСПРАВЛЕНО: используем avatars_src и avatars_dst ---
            shutil.copytree(avatars_src, avatars_dst)
            print(f"[+] Скопированы аватары из '{avatars_src}' в '{avatars_dst}'")

        print(f"[+] Генерация веб-сайта завершена.")

# --- Функция для вызова из tg_archive.py ---
def generate_website(config): # Принимаем config напрямую
    db_path = config["storage"]["database"]
    output_dir = config["storage"].get("output_dir", "output") # Используем output_dir из конфига
    generator = WebGenerator(config, db_path, output_dir) # Передаём config
    generator.generate()
# УБРАЛИ ИМПОРТ load_config
# from tg_archive import load_config
