# web_gen/html_generator.py
import json
import os
import sqlite3
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, timezone
from web_gen.db_queries import (
    get_db_stats, get_topics, get_topic_info,
    get_messages_for_topic, get_total_message_pages_for_topic
)
from database import get_generation_run_count, increment_generation_run_count

class HTMLGenerator:
    def __init__(self, config, db_path, output_dir):
        self.config = config
        self.db_path = db_path
        self.output_dir = output_dir
        self.jinja_env = Environment(loader=FileSystemLoader('templates'), autoescape=True)
        self.index_template = self.jinja_env.get_template('index.html.j2')
        self.topic_template = self.jinja_env.get_template('topic.html.j2')
        self.message_template = self.jinja_env.get_template('message.html.j2')
        self.default_avatar = self._resolve_default_avatar()
        self.banner = self._resolve_banner()
        self.message_layout = ((self.config.get('ui') or {}).get('message_layout') or 'side').lower()
        if self.message_layout not in ('side', 'stacked'):
            self.message_layout = 'side'

    def _resolve_banner(self):
        """Баннер в шапке: файл копируется в корень output под именем banner.<ext>."""
        banner_cfg = (self.config.get('ui') or {}).get('banner') or {}
        path = banner_cfg.get('path')
        if not path or not os.path.exists(path):
            return None
        ext = os.path.splitext(path)[1].lower() or '.jpg'
        return {'url': f"/banner{ext}", 'alt': banner_cfg.get('alt', '')}

    @staticmethod
    def group_messages(messages):
        """Склеивает подряд идущие сообщения одного альбома в одну карточку."""
        groups = []
        current = None
        for msg in messages:
            gid = msg.get('grouped_id')
            if gid and current is not None and current['grouped_id'] == gid:
                current['messages'].append(msg)
            else:
                current = {'grouped_id': gid, 'messages': [msg]}
                groups.append(current)
        for group in groups:
            # В ленте сообщения идут от новых к старым, внутри альбома — по порядку.
            group['messages'].sort(key=lambda m: m['id'])
            group['is_album'] = bool(group['grouped_id']) and len(group['messages']) > 1
        return groups

    def _resolve_default_avatar(self):
        """Путь к аватарке-заглушке в терминах сгенерированного сайта.

        Медиа публикуются в media/original/, поэтому настроенный
        ``media/default_avatar.jpg`` превращается в ``media/original/default_avatar.jpg``.
        """
        raw = (self.config.get('ui') or {}).get('default_avatar_path')
        if not raw:
            return None
        if raw.startswith('media/'):
            return 'media/original/' + raw[len('media/'):]
        return raw

    def _write_topics_json(self, topics_list, generated_at=None, show_update_time=True):
        """Список тем и метаданные генерации для страницы поиска (Flask читает из output)."""
        data = {
            'generated_at': generated_at,
            'show_update_time': bool(show_update_time) if generated_at else False,
            'topics': [{
                'id': t['id'],
                'title': t['title'],
                'icon_emoji': t['icon_emoji'] or '',
                'message_count': t['message_count'],
                'url': f"/topics/topic_{t['id']}_page_1.html",
            } for t in topics_list],
        }
        path = os.path.join(self.output_dir, 'topics.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def generate(self):
        print(f"[*] Генерация HTML веб-сайта в '{self.output_dir}'...")
        os.makedirs(self.output_dir, exist_ok=True)

        topics_output_dir = os.path.join(self.output_dir, 'topics')
        messages_output_dir = os.path.join(self.output_dir, 'messages')
        os.makedirs(topics_output_dir, exist_ok=True)
        os.makedirs(messages_output_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Время обновления — в UTC: местное время сдаёт часовой пояс владельца.
        generation_time = datetime.now(timezone.utc)
        generation_date = generation_time.strftime('%Y-%m-%d %H:%M')
        new_run_count = increment_generation_run_count(conn)
        show_update_time = (self.config.get('ui') or {}).get('show_update_time', True)

        # --- 1. Главная страница ---
        total_messages, total_topics, most_active_topic = get_db_stats(conn)
        topics_list = get_topics(conn, self.config.get('ui', {}).get('topics_ranking', 'by_messages'), config=self.config)
        for topic in topics_list:
            topic['first_page_filename'] = f"topics/topic_{topic['id']}_page_1.html"
        self._write_topics_json(topics_list, generation_date, show_update_time)

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
            'topics': topics_list,
            'banner': self.banner,
            'message_layout': self.message_layout,
            'show_update_time': show_update_time,
            'config': self.config,
            'generation_date': generation_date,
            'generation_run_number': new_run_count
        }
        index_html_content = self.index_template.render(**index_context)
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(index_html_content)
        print(f"[+] Сгенерирована главная страница: index.html")

        # --- 2. Страницы тем и отдельные сообщения ---
        generate_message_pages = self.config.get('ui', {}).get('generate_message_pages', True)
        messages_per_page = self.config.get('ui', {}).get('messages_per_page', 50)

        for topic in topics_list:
            topic_id = topic['id']
            print(f"[DEBUG] Обработка темы: {topic_id} - {topic['title']}")
            topic_info = get_topic_info(conn, topic_id, config=self.config)
            if not topic_info:
                print(f"[WARNING] Тема {topic_id} не найдена, пропуск.")
                continue

            total_pages = get_total_message_pages_for_topic(conn, topic_id, messages_per_page)
            order = self.config.get('ui', {}).get('messages_order', 'newest_first')
            if total_pages == 0:
                continue

            all_messages_for_topic = []
            if generate_message_pages:
                # Соберём все сообщения темы для генерации отдельных страниц
                for page_num in range(1, total_pages + 1):
                    page_messages = get_messages_for_topic(
                        conn, topic_id, order, page_num, messages_per_page, config=self.config
                    )
                    all_messages_for_topic.extend(page_messages)

            # --- Генерация страниц темы ---
            for page_num in range(1, total_pages + 1):
                messages = get_messages_for_topic(
                    conn, topic_id, order, page_num, messages_per_page, config=self.config
                )
                filename = f"topic_{topic_id}_page_{page_num}.html"
                topic_context = {
                    'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
                    'site_description': self.config.get('site', {}).get('description', ''),
                    'footer_text': self.config.get('site', {}).get('footer_text', ''),
                    'default_theme': self.config.get('ui', {}).get('theme', 'light'),
                    'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
                    'ticker_texts': self.config.get('ticker', {}).get('texts', []),
                    'useful_links': self.config.get('useful_links', []),
                    'topics': topics_list,
                    'current_topic': topic_info,
                    'messages': messages,
                    'message_groups': self.group_messages(messages),
                    'current_page': page_num,
                    'total_pages': total_pages,
                    'page_links': range(1, total_pages + 1),
                    'messages_order': order,
                    'show_order_label': order == 'newest_first',
                    'default_avatar': self.default_avatar,
                    'banner': self.banner,
                    'message_layout': self.message_layout,
                    'show_update_time': show_update_time,
                    'config': self.config,
                    'generation_date': generation_date,
                    'generation_run_number': new_run_count
                }
                topic_html_content = self.topic_template.render(**topic_context)
                output_file_path = os.path.join(topics_output_dir, filename)
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(topic_html_content)
                print(f"[+] Сгенерирована страница темы: topics/{filename}")

            # --- Генерация отдельных страниц сообщений ---
            if generate_message_pages:
                for msg in all_messages_for_topic:
                    message_context = {
                        'site_title': self.config.get('site', {}).get('title', 'Telegram Archive'),
                        'site_description': self.config.get('site', {}).get('description', ''),
                        'footer_text': self.config.get('site', {}).get('footer_text', ''),
                        'default_theme': self.config.get('ui', {}).get('theme', 'light'),
                        'ticker_enabled': self.config.get('ticker', {}).get('enabled', False),
                        'ticker_texts': self.config.get('ticker', {}).get('texts', []),
                        'useful_links': self.config.get('useful_links', []),
                        'topics': topics_list,
                        'current_topic': topic_info,
                        'message': msg,
                        'default_avatar': self.default_avatar,
                        'banner': self.banner,
                        'message_layout': self.message_layout,
                        'show_update_time': show_update_time,
                        'config': self.config,
                        'generation_date': generation_date,
                        'generation_run_number': new_run_count
                    }
                    msg_filename = f"message_{msg['id']}.html"
                    msg_html_content = self.message_template.render(**message_context)
                    msg_output_path = os.path.join(messages_output_dir, msg_filename)
                    with open(msg_output_path, 'w', encoding='utf-8') as f:
                        f.write(msg_html_content)
                print(f"[+] Сгенерировано {len(all_messages_for_topic)} отдельных страниц сообщений для темы {topic_id}")

        conn.close()
        print(f"[+] Генерация HTML завершена.")
