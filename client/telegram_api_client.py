# client/telegram_api_client.py
import os
import asyncio
from typing import List, Dict, Any, Optional
from telethon import TelegramClient
from telethon.tl.types import PeerChannel, Message, User
from telethon.tl.functions.channels import GetForumTopicsRequest

class TelegramAPIClient:
    """
    Класс для взаимодействия с Telegram API.
    Инициализирует клиент и предоставляет методы для получения данных.
    """
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
        self._started = False

    async def start(self):
        """Запуск клиента и авторизация."""
        if not self._started:
            await self.client.start()
            self._started = True
            print("[+] Telegram API клиент запущен")

    async def get_topics(self) -> List[Dict[str, Any]]:
        """Получает список тем форума."""
        if not self._started:
            raise RuntimeError("Клиент не запущен. Вызовите start() перед использованием.")

        result = await self.client(GetForumTopicsRequest(
            channel=PeerChannel(channel_id=abs(self.group_id)),
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        topics = []
        for topic in result.topics:
            # print(f"[DEBUG] Topic ID: {topic.id}, Title: '{topic.title}', Icon Emoji Attr: {hasattr(topic, 'icon_emoji')}, Icon Emoji Value: {getattr(topic, 'icon_emoji', 'ATTR_NOT_FOUND')}, Type: {type(getattr(topic, 'icon_emoji', 'ATTR_NOT_FOUND'))}")
            topics.append({
                'telegram_id': topic.id,
                'title': topic.title,
                'icon_emoji': getattr(topic, 'icon_emoji', None),
                'is_closed': getattr(topic, 'closed', False),
                'created_at': getattr(topic, 'date', None)
            })
        return topics

    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0, limit: int = 100, reverse: bool = True) -> List[Message]:
        """Получает сообщения из темы или из общего чата."""
        if not self._started:
            raise RuntimeError("Клиент не запущен. Вызовите start() перед использованием.")

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

    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """Получает информацию о пользователе."""
        if not self._started:
            raise RuntimeError("Клиент не запущен. Вызовите start() перед использованием.")

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

    async def close(self):
        """Закрывает клиент."""
        if self._started:
            await self.client.disconnect()
            self._started = False
