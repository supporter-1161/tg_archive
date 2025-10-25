# telegram_client.py
# Импортируем наши новые классы
from client.telegram_api_client import TelegramAPIClient
from client.message_processor import MessageProcessor
from client.sync_logic import SyncLogic
from typing import List, Dict, Any, Optional
from database import get_db_connection
from telethon.tl.types import Message

class TelegramArchiver:
    def __init__(self, api_id: str, api_hash: str, session_name: str, group_id: int, sync_direction: str = 'forward'):
        self.api_client = TelegramAPIClient(api_id, api_hash, session_name, group_id)
        self.sync_direction = sync_direction
        self.group_id = group_id

    async def start(self):
        """Запуск внутреннего клиента."""
        await self.api_client.start()

    async def get_topics(self) -> List[Dict[str, Any]]:
        """Получает список тем через API клиент."""
        return await self.api_client.get_topics()

    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0, limit: int = 100, reverse: Optional[bool] = None) -> List[Message]:
        """Получает сообщения через API клиент, учитывая sync_direction."""
        if reverse is None:
            reverse = (self.sync_direction == 'backward')
        return await self.api_client.get_messages(topic_id=topic_id, offset_id=offset_id, limit=limit, reverse=reverse)

    async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None, sync_direction: str = 'forward'):
        """Синхронизирует темы и сообщения, используя SyncLogic."""
        message_processor = MessageProcessor(self.api_client, db_path)
        sync_logic = SyncLogic(self.api_client, message_processor)
        # Вызываем метод синхронизации
        await sync_logic.sync_topics_and_messages(db_path, media_dir, verbose, topic_ids, sync_direction)

    async def close(self):
        """Закрывает внутренний клиент."""
        await self.api_client.close()
