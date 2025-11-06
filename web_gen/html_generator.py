# web_gen/html_generator.py
import os
import sqlite3
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from web_gen.db_queries import get_db_stats, get_topics, get_topic_info, get_messages_for_topic, get_total_message_pages_for_topic
from database import get_generation_run_count, increment_generation_run_count

class HTMLGenerator:
    """
    Класс для генерации HTML-файлов веб-сайта.
    """
    def __init__(self, config, db_path, output_dir):
        self.config = config
        self.db_path = db_path
        self.output_dir = output_dir
        self.jinja_env = Environment(loader=FileSystemLoader('templates'), autoescape=True)
        self.index_template = self.jinja_env.get_template('index.html.j2')
        self.topic_template = self.jinja_env.get_template('topic.html.j2')

    def generate(self):
        print(f"[*] Генерация HTML веб-сайта в '{self.output_dir}'...")
        os.makedirs(self.output_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Для доступа к колонкам по имени

        #Получаем время и счётчик запусков ---
        generation_time = datetime.now()
        generation_date = generation_time.strftime('%Y-%m-%d %H:%M:%S') # Форматируем как строку
        current_run_count = get_generation_run_count(conn) # Получаем текущее значение
        new_run_count = increment_generation_run_count(conn) # Увеличиваем и получаем новое
        print(f"[DEBUG] Счётчик запусков до увеличения: {current_run_count}, после: {new_run_count}")

        # --- 1. Генерация главной страницы ---
        total_messages, total_topics, most_active_topic = get_db_stats(conn) # <-- Используем импортированную функцию
        topics = get_topics(conn, self.config.get('ui', {}).get('topics_ranking', 'by_messages'), config=self.config) # <-- Используем импортированную функцию
        messages_per_page = self.config.get('ui', {}).get('messages_per_page', 50)

        # Подготовка данных для шаблона индекса (включая имена файлов страниц тем)
        for topic in topics:
            topic_telegram_id = topic['id']
            # ВСЕГДА используем _page_1.html
            first_page_filename = f"topic_{topic_telegram_id}_page_1.html"
            topic['first_page_filename'] = first_page_filename

        index_context = {
            'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
            'site_description': self.config.get('site', {}).get('description', ''),
            'footer_text': self.config.get('site', {}).get('footer_text', ''),
            'default_theme': self.config.get('ui', {}).get('theme', 'light'),
            'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
            'ticker_texts': self.config.get('ticker', {}).get('texts', []),
            'useful_links': self.config.get('useful_links', []),
            'total_messages': total_messages,
            'total_topics': total_topics,
            'most_active_topic': most_active_topic,
            'topics': topics,
            'config': self.config,
            # --- НОВОЕ: Добавляем generation_date и generation_run_number ---
            'generation_date': generation_date,
            'generation_run_number': new_run_count
            # --- КОНЕЦ НОВОГО ---
        }

        index_html_content = self.index_template.render(**index_context)
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(index_html_content)
        print(f"[+] Сгенерирована главная страница: index.html")

        # --- 2. Генерация страниц тем ---
        for topic in topics:
            topic_id = topic['id']
            print(f"[DEBUG] Обработка темы: {topic_id} - {topic['title']}")
            topic_info = get_topic_info(conn, topic_id, config=self.config) # <-- Используем импортированную функцию
            if not topic_info:
                print(f"[WARNING] Информация о теме {topic_id} не найдена, пропуск.")
                continue

            total_pages = get_total_message_pages_for_topic(conn, topic_id, messages_per_page) # <-- Используем импортированную функцию
            order = self.config.get('ui', {}).get('messages_order', 'newest_first')

            if total_pages == 0:
                print(f"[DEBUG] Для темы {topic_id} нет сообщений, пропускаем генерацию страниц темы.")
                continue

            for page_num in range(1, total_pages + 1):
                print(f"[DEBUG] Обработка страницы {page_num} для темы {topic_id}")
                messages = get_messages_for_topic(conn, topic_id, order, page_num, messages_per_page, config=self.config) # <-- Используем импортированную функцию
                filename = f"topic_{topic_id}_page_{page_num}.html"

                topic_context = {
                    'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
                    'site_description': self.config.get('site', {}).get('description', ''),
                    'footer_text': self.config.get('site', {}).get('footer_text', ''),
                    'default_theme': self.config.get('ui', {}).get('theme', 'light'),
                    'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
                    'ticker_texts': self.config.get('ticker', {}).get('texts', []),
                    'useful_links': self.config.get('useful_links', []),
                    'topics': topics,
                    'current_topic': topic_info,
                    'messages': messages,
                    'current_page': page_num,
                    'total_pages': total_pages,
                    'page_links': range(1, total_pages + 1),
                    'messages_order': order,
                    'show_order_label': order == 'newest_first',
                    'config': self.config,
                    # --- НОВОЕ: Добавляем generation_date и generation_run_number ---
                    'generation_date': generation_date,
                    'generation_run_number': new_run_count
                    # --- КОНЕЦ НОВОГО ---
                }

                topic_html_content = self.topic_template.render(**topic_context)
                output_file_path = os.path.join(self.output_dir, filename)
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(topic_html_content)
                print(f"[+] Сгенерирована страница темы: {filename} (Страница {page_num}/{total_pages})")

        conn.close()
        print(f"[+] Генерация HTML завершена.")
