# telegram_client.py
# Импортируем наши новые классы
from client.telegram_api_client import TelegramAPIClient
from client.message_processor import MessageProcessor
from client.sync_logic import SyncLogic
from typing import List, Dict, Any, Optional
from database import get_db_connection
from telethon.tl.types import Message
import os
import time
import random
import asyncio

class TelegramArchiver:
    def __init__(self, api_id: str, api_hash: str, session_name: str, group_id: int, sync_direction: str = 'forward'):
        # Теперь используем TelegramAPIClient
        self.api_client = TelegramAPIClient(api_id, api_hash, session_name, group_id)
        # Сохраняем направление синхронизации
        self.sync_direction = sync_direction
        # И group_id, если понадобится
        self.group_id = group_id

    async def start(self):
        """Запуск внутреннего клиента."""
        await self.api_client.start()

    # --- ИЗМЕНЕНИЕ get_topics (используем api_client) ---
    async def get_topics(self) -> List[Dict[str, Any]]:
        """Получает список тем через API клиент."""
        return await self.api_client.get_topics()
    # --- КОНЕЦ ИЗМЕНЕНИЯ get_topics ---

    # --- ИЗМЕНЕНИЕ get_messages (учёт sync_direction, используем api_client) ---
    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0, limit: int = 100, reverse: Optional[bool] = None) -> List[Message]:
        """Получает сообщения через API клиент, учитывая sync_direction."""
        if reverse is None:
            reverse = (self.sync_direction == 'backward')
        return await self.api_client.get_messages(topic_id=topic_id, offset_id=offset_id, limit=limit, reverse=reverse)
    # --- КОНЕЦ ИЗМЕНЕНИЯ get_messages ---

    # --- ИЗМЕНЕНИЕ sync_topics_and_messages (удалён, используем SyncLogic) ---
    # async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None, sync_direction: str = 'forward'):
    #     # Эта логика перенесена в SyncLogic
    #     pass
    # --- КОНЕЦ ИЗМЕНЕНИЯ sync_topics_and_messages ---

    # --- НОВЫЙ МЕТОД: sync_topics_and_messages (обёртка для SyncLogic) ---
    async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None, sync_direction: str = 'forward'):
        """Синхронизирует темы и сообщения, используя SyncLogic."""
        # Создаём MessageProcessor
        message_processor = MessageProcessor(self.api_client, db_path)
        # Создаём SyncLogic
        sync_logic = SyncLogic(self.api_client, message_processor)
        # Вызываем метод синхронизации
        await sync_logic.sync_topics_and_messages(db_path, media_dir, verbose, topic_ids, sync_direction)
    # --- КОНЕЦ НОВОГО МЕТОДА ---

    async def close(self):
        """Закрывает внутренний клиент."""
        await self.api_client.close()
