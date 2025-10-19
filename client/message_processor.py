# client/message_processor.py
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from database import get_db_connection, save_user, get_file_path_by_media_info, save_media_file_info
import os
import asyncio
import json
from typing import Dict, Any, Optional

class MessageProcessor:
    """
    Класс для обработки отдельных сообщений Telegram.
    Включает скачивание медиа и преобразование сообщения в словарь.
    """
    def __init__(self, api_client, db_path: str):
        self.api_client = api_client
        self.db_path = db_path

    # --- ИЗМЕНЕНИЕ download_media (принимает topic_id, использует self.api_client и self.db_path) ---
    async def download_media(self, message: Message, media_dir: str, topic_id: Optional[int] = None) -> Optional[str]:
        """Скачивает медиа из сообщения, избегая дубликатов, и возвращает путь."""
        if not message.media:
            return None

        # --- ИЗВЛЕЧЕНИЕ ИДЕНТИФИКАТОРОВ МЕДИА ---
        media_obj = message.media
        if hasattr(media_obj, 'photo') and media_obj.photo:
            # Для фото
            media_id = media_obj.photo.id
            access_hash = media_obj.photo.access_hash
        elif hasattr(media_obj, 'document') and media_obj.document:
            # Для документа/видео/аудио
            media_id = media_obj.document.id
            access_hash = media_obj.document.access_hash
        else:
            # Неизвестный тип медиа или нет id/access_hash
            # Возвращаем None, чтобы избежать скачивания, или продолжить старую логику
            print(f"    [WARNING] Медиа без id/access_hash (msg.id={message.id}), возможно дубликат.")
            # --- ПУТЬ СОХРАНЕНИЯ (Старая логика) ---
            sub_dir = f"topics/{topic_id}" if topic_id else "global"
            save_dir = os.path.join(media_dir, sub_dir)
            os.makedirs(save_dir, exist_ok=True)
            # --- СКАЧИВАНИЕ (Старая логика) ---
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    file_path = await message.download_media(file=save_dir)
                    return file_path # Возвращаем путь к скачанному файлу
                except Exception as e:
                    if "Timeout" in str(e) or "Request was unsuccessful" in str(e):
                        print(f"[!] Ошибка при скачивании медиа (msg.id={message.id}, попытка {attempt + 1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2) # Пауза перед повтором
                            continue
                    else:
                        print(f"[!] Ошибка при скачивании медиа (msg.id={message.id}): {e}")
                    return None
            return None # Если все попытки не удались

        # --- ПРОВЕРКА НА СУЩЕСТВОВАНИЕ В БД ---
        conn = get_db_connection(self.db_path)
        existing_path = get_file_path_by_media_info(conn, media_id, access_hash)
        conn.close()

        if existing_path:
            # Файл уже был скачан, используем существующий путь
            if os.path.exists(existing_path): # Проверяем, не был ли файл удалён вручную
                print(f"    [CACHE:{topic_id}] Используем кэшированный файл для media_id={media_id}")
                return existing_path
            else:
                print(f"    [CACHE:{topic_id}] Кэшированный файл не найден на диске: {existing_path}. Скачиваем заново.")
                # Продолжаем скачивание

        # --- ОПРЕДЕЛЕНИЕ ТИПА МЕДИА ---
        media_type = None
        if isinstance(media_obj, MessageMediaPhoto):
            media_type = 'photo'
        elif isinstance(media_obj, MessageMediaDocument):
            mime_type = getattr(media_obj.document, 'mime_type', '')
            if 'video' in mime_type:
                media_type = 'video'
            elif 'audio' in mime_type:
                media_type = 'audio'
            else:
                media_type = 'document'
        if not media_type:
            return None

        # --- ПУТЬ СОХРАНЕНИЯ ---
        sub_dir = f"topics/{topic_id}" if topic_id else "global"
        save_dir = os.path.join(media_dir, sub_dir)
        os.makedirs(save_dir, exist_ok=True)

        # --- СКАЧИВАНИЕ ---
        max_retries = 3
        for attempt in range(max_retries):
            try:
                file_path = await message.download_media(file=save_dir)
                if file_path: # Если скачивание прошло успешно
                    # --- СОХРАНЕНИЕ ИНФОРМАЦИИ О ФАЙЛЕ В БД ---
                    conn = get_db_connection(self.db_path)
                    save_media_file_info(conn, media_id, access_hash, file_path)
                    conn.close()
                    print(f"    [DOWNLOAD:{topic_id}] Скачан новый файл для media_id={media_id}, путь: {file_path}")
                    return file_path # Возвращаем путь к скачанному файлу
                else:
                    print(f"[!] Ошибка при скачивании медиа (media_id={media_id}): путь не получен")
                    return None
            except Exception as e:
                if "Timeout" in str(e) or "Request was unsuccessful" in str(e):
                    print(f"[!] Ошибка при скачивании медиа (media_id={media_id}, попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2) # Пауза перед повтором
                        continue
                else:
                    print(f"[!] Ошибка при скачивании медиа (media_id={media_id}): {e}")
                return None

        return None # Если все попытки не удались
    # --- КОНЕЦ ИЗМЕНЕНИЯ download_media ---

    # --- ИЗМЕНЕНИЕ message_to_dict (добавлено поле file_extension) ---
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
            'user_id': msg.sender_id or 0,
            'text': msg.text or '',  # Даже если текста нет — сохраняем пустую строку
            'timestamp': msg.date.isoformat(),
            'reply_to': getattr(msg.reply_to, 'reply_to_msg_id', None) if msg.reply_to else None,
            'media_type': None,  # Будет заполнено позже
            'media_path': None,  # Будет заполнено позже
            'poll_data': poll_data,
            'file_extension': None # <-- Новое поле
        }
    # --- КОНЕЦ ИЗМЕНЕНИЯ message_to_dict ---

    # --- НОВЫЙ МЕТОД: process_user ---
    async def process_user(self, conn, user_id: int):
        """Получает информацию о пользователе через API клиент и сохраняет в БД."""
        if user_id:
            # Используем метод из TelegramAPIClient
            user_info = await self.api_client.get_user_info(user_id)
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
    # --- КОНЕЦ НОВОГО МЕТОДА ---
