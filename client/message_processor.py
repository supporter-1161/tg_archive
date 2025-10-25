# client/message_processor.py
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from database import get_db_connection, save_user, get_file_path_by_media_info, save_media_file_info
import os
import asyncio
import json
from typing import Dict, Any, Optional

def human_readable_size(size_bytes: int) -> str:
    """Преобразует размер в байтах в человекочитаемый формат."""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

class MessageProcessor:
    """
    Класс для обработки отдельных сообщений Telegram.
    Включает скачивание медиа и преобразование сообщения в словарь.
    """
    def __init__(self, api_client, db_path: str):
        self.api_client = api_client
        self.db_path = db_path

    async def download_media(self, message: Message, media_dir: str, topic_id: Optional[int] = None) -> Optional[str]:
        """Скачивает медиа из сообщения, избегая дубликатов, и возвращает путь."""
        if not message.media:
            return None
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
            sub_dir = f"topics/{topic_id}" if topic_id else "global"
            save_dir = os.path.join(media_dir, sub_dir)
            os.makedirs(save_dir, exist_ok=True)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    file_path = await message.download_media(file=save_dir)
                    if file_path and os.path.exists(file_path):
                        # Получаем размер скачанного файла
                        file_size_bytes = os.path.getsize(file_path)
                        file_size_str = human_readable_size(file_size_bytes)
                        print(f"    [SIZE:{topic_id}] Размер файла {file_path}: {file_size_bytes} байт ({file_size_str})")
                        # Сохраняем информацию о файле в БД, включая размер
                        conn = get_db_connection(self.db_path)
                        save_media_file_info(conn, media_id, access_hash, file_path, file_size_bytes)
                        conn.close()
                        return file_path # Возвращаем путь к скачанному файлу
                    else:
                        print(f"[!] Ошибка при скачивании медиа (msg.id={message.id}): путь не получен или файл не найден")
                        return None
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
                # Проверим, есть ли размер файла в БД, если нет - посчитаем и сохраним
                conn = get_db_connection(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT file_size FROM media_files WHERE file_path = ?", (existing_path,))
                row = cursor.fetchone()
                conn.close()
                if row and row[0] is not None:
                    print(f"    [SIZE:{topic_id}] Размер файла {existing_path} из БД: {human_readable_size(row[0])}")
                else:
                    # Размер неизвестен, получим его из файловой системы
                    if os.path.exists(existing_path):
                        file_size_bytes = os.path.getsize(existing_path)
                        print(f"    [SIZE:{topic_id}] Размер файла {existing_path} из ФС: {human_readable_size(file_size_bytes)}")
                        # Обновим запись в БД с размером
                        conn = get_db_connection(self.db_path)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE media_files SET file_size = ? WHERE file_path = ?", (file_size_bytes, existing_path))
                        conn.commit()
                        conn.close()
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
                if file_path and os.path.exists(file_path): # Если скачивание прошло успешно и файл существует
                    # Получаем размер скачанного файла
                    file_size_bytes = os.path.getsize(file_path)
                    file_size_str = human_readable_size(file_size_bytes)
                    print(f"    [DOWNLOAD:{topic_id}] Скачан новый файл для media_id={media_id}, путь: {file_path}, размер: {file_size_bytes} байт ({file_size_str})")
                    # --- СОХРАНЕНИЕ ИНФОРМАЦИИ О ФАЙЛЕ В БД (включая размер) ---
                    conn = get_db_connection(self.db_path)
                    save_media_file_info(conn, media_id, access_hash, file_path, file_size_bytes)
                    conn.close()
                    return file_path # Возвращаем путь к скачанному файлу
                else:
                    print(f"[!] Ошибка при скачивании медиа (media_id={media_id}): путь не получен или файл не найден после скачивания")
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
