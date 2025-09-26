from telethon import TelegramClient
from telethon.tl.types import PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument
from telethon.tl.functions.channels import GetForumTopicsRequest
import os
import asyncio
from typing import List, Dict, Any, Optional
import json
from database import get_db_connection, save_topic, get_last_message_id, update_last_message_id, save_user, save_message
import time
import random

class TelegramArchiver:
    def __init__(self, api_id: str, api_hash: str, session_name: str, group_id: int):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_name = session_name
        self.group_id = group_id

        # Реалистичные параметры для обхода защиты
        self.client = TelegramClient(
            session=session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            app_version='10.4.2',
            device_model='SM-G991B',
            system_version='14'
        )

    async def start(self):
        """Запуск клиента и авторизация."""
        await self.client.start()
        print("[+] Telegram клиент запущен")

    async def get_topics(self) -> List[Dict[str, Any]]:
        """Получает список тем форума."""
        result = await self.client(GetForumTopicsRequest(
            channel=PeerChannel(channel_id=abs(self.group_id)),
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        topics = []
        for topic in result.topics:
            topics.append({
                'telegram_id': topic.id,
                'title': topic.title,
                'icon_emoji': topic.icon_emoji if hasattr(topic, 'icon_emoji') else None,
                'is_closed': getattr(topic, 'closed', False),
                'created_at': getattr(topic, 'date', None)
            })
        return topics

    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0, limit: int = 100, reverse: bool = True) -> List[Message]:
        """Получает сообщения из темы или из общего чата."""
        if topic_id:
            # Фильтр по теме
            messages = await self.client.get_messages(
                PeerChannel(channel_id=abs(self.group_id)),
                limit=limit,
                offset_id=offset_id,
                filter=None,
                reply_to=topic_id,
                reverse=reverse
            )
        else:
            # Глобальные сообщения (без тем)
            messages = await self.client.get_messages(
                PeerChannel(channel_id=abs(self.group_id)),
                limit=limit,
                offset_id=offset_id,
                filter=None,
                reverse=reverse
            )
        return messages

    async def download_media(self, message: Message, media_dir: str, topic_id: Optional[int] = None) -> Optional[str]:
        """Скачивает медиа из сообщения и возвращает путь."""
        if not message.media:
            return None
        # Определяем тип медиа
        media_type = None
        if isinstance(message.media, MessageMediaPhoto):
            media_type = 'photo'
        elif isinstance(message.media, MessageMediaDocument):
            mime_type = getattr(message.media.document, 'mime_type', '')
            if 'video' in mime_type:
                media_type = 'video'
            elif 'audio' in mime_type:
                media_type = 'audio'
            else:
                media_type = 'document'
        if not media_type:
            return None
        # Путь сохранения
        sub_dir = f"topics/{topic_id}" if topic_id else "global"
        save_dir = os.path.join(media_dir, sub_dir)
        os.makedirs(save_dir, exist_ok=True)
        # Скачивание с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                file_path = await message.download_media(file=save_dir)
                return file_path
            except Exception as e:
                if "Timeout" in str(e) or "Request was unsuccessful" in str(e):
                    print(f"[!] Ошибка при скачивании медиа (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)  # Пауза перед повтором
                        continue
                else:
                    print(f"[!] Ошибка при скачивании медиа: {e}")
                return None

    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """Получает информацию о пользователе."""
        try:
            entity = await self.client.get_entity(user_id)
            return {
                'telegram_id': entity.id,
                'username': getattr(entity, 'username', None),
                'first_name': getattr(entity, 'first_name', ''),
                'last_name': getattr(entity, 'last_name', ''),
            }
        except Exception as e:
            print(f"[!] Ошибка при получении пользователя {user_id}: {e}")
            return {
                'telegram_id': user_id,
                'username': None,
                'first_name': 'Unknown',
                'last_name': 'User',
            }

    def message_to_dict(self, msg: Message, topic_id: Optional[int] = None) -> Dict[str, Any]:
        """Преобразует объект сообщения в словарь для сохранения."""
        poll_data = None
        if msg.poll:
            poll_data = json.dumps({
                'question': msg.poll.poll.question,
                'answers': [{'text': a.text, 'votes': a.voters} for a in msg.poll.poll.answers],
                'total_voters': msg.poll.poll.total_voters
            })
        return {
            'telegram_id': msg.id,
            'topic_id': topic_id,
            'user_id': msg.sender_id or 0,  # Обязательно
            'text': msg.text,
            'timestamp': msg.date.isoformat(),
            'reply_to': getattr(msg.reply_to, 'reply_to_msg_id', None) if msg.reply_to else None,
            'media_type': None,
            'media_path': None,
            'poll_data': poll_data
        }

    async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None):
        """Синхронизирует темы и сообщения."""
        conn = get_db_connection(db_path)
        # Получаем темы
        topics = await self.get_topics()
        print(f"[+] Найдено тем: {len(topics)}")
        # Фильтруем по ID, если указаны
        if topic_ids:
            topics = [t for t in topics if t['telegram_id'] in topic_ids]
            print(f"[+] Отфильтровано до {len(topics)} тем: {topic_ids}")
        # Сохраняем темы в БД
        for topic in topics:
            save_topic(conn, topic)
        # Цикл по темам
        for topic in topics:
            topic_id = topic['telegram_id']
            last_msg_id = get_last_message_id(conn, topic_id) or 0
            offset_id = 0  # Начинаем с самого начала

            print(f"[*] Обработка темы: [{topic_id}] {topic['title']} (offset: {offset_id}, last_msg_id: {last_msg_id})")

            while True:
                messages = await self.get_messages(topic_id=topic_id, offset_id=offset_id, limit=100, reverse=True)
                
                if verbose:
                    print(f"  [DEBUG:{topic_id}] Получено {len(messages)} сообщений (offset_id={offset_id})")
                
                if not messages:
                    if verbose:
                        print(f"  [DEBUG:{topic_id}] Нет новых сообщений, выходим из цикла")
                    break

                # Логируем ID сообщений
                if verbose:
                    msg_ids = [msg.id for msg in messages]
                    print(f"  [DEBUG:{topic_id}] IDs сообщений: {msg_ids[:10]}{'...' if len(msg_ids) > 10 else ''}")

                for msg in messages:
                    if verbose:
                        print(f"    [DEBUG:{topic_id}] Обработка msg.id={msg.id}, last_msg_id={last_msg_id}")

                    if msg.id <= last_msg_id:
                        if verbose:
                            print(f"      [SKIP:{topic_id}] Пропускаем (уже есть)")
                        continue  # Пропускаем уже сохранённые

                    # Обработка пользователя (только если есть sender_id)
                    if msg.sender_id:
                        user_info = await self.get_user_info(msg.sender_id)
                        save_user(conn, user_info)
                    else:
                        # Для системных сообщений — используем заглушку
                        user_info = {
                            'telegram_id': 0,
                            'username': 'system',
                            'first_name': 'System',
                            'last_name': '',
                        }
                        save_user(conn, user_info)

                    # Скачивание медиа
                    media_path = await self.download_media(msg, media_dir, topic_id)

                    # Подготовка данных для сохранения
                    msg_dict = self.message_to_dict(msg, topic_id)
                    msg_dict['media_path'] = media_path
                    if media_path:
                        _, ext = os.path.splitext(media_path)
                        msg_dict['media_type'] = ext[1:]

                    save_message(conn, msg_dict)
                    if verbose:
                        print(f"      [SAVE:{topic_id}] Сохранено сообщение {msg.id}")

                    # Обновляем last_message_id
                    if msg.id > last_msg_id:
                        last_msg_id = msg.id
                        update_last_message_id(conn, topic_id, last_msg_id)
                        if verbose:
                            print(f"      [UPDATE:{topic_id}] last_msg_id обновлён до {last_msg_id}")

                # Смещаем offset для следующей пачки
                # При reverse=True: offset_id должен быть минимальным ID в пачке
                offset_id = min(msg.id for msg in messages)  # Это правильный способ
                if verbose:
                    print(f"      [OFFSET:{topic_id}] offset_id обновлён до {offset_id}")

                # Задержка между запросами (0.5–1.5 секунды)
                delay = random.uniform(0.5, 1.5)
                if verbose:
                    print(f"      [SLEEP:{topic_id}] Задержка {delay:.2f} секунд...")
                time.sleep(delay)

        conn.close()
        print("[+] Синхронизация завершена")

    async def close(self):
        """Закрывает клиент."""
        await self.client.disconnect()

