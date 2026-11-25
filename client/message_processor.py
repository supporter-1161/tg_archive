# client/message_processor.py
"""Преобразование сообщений Telegram в записи БД + скачивание медиа."""
import asyncio
import json
import os
import re
from typing import Dict, Any, Optional

from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from database import (
    get_file_path_by_media_info,
    get_file_size_by_path,
    get_user,
    save_media_file_info,
    save_user,
)
from utils import human_readable_size

__all__ = ['MessageProcessor', 'media_info', 'human_readable_size', 'SYSTEM_USER']

SYSTEM_USER = {
    'telegram_id': 0,
    'username': 'system',
    'first_name': 'System',
    'last_name': '',
}


def _safe_filename(name: str, fallback: str) -> str:
    name = os.path.basename(name or '').strip()
    name = re.sub(r'[\x00-\x1f/\\]', '_', name)
    if not name:
        return fallback
    return name[:120]


def media_info(message: Message):
    """Возвращает (media_id, access_hash, media_type) или None для не-файловых медиа."""
    media = message.media
    if isinstance(media, MessageMediaPhoto) and getattr(media, 'photo', None):
        return media.photo.id, media.photo.access_hash, 'photo'
    if isinstance(media, MessageMediaDocument) and getattr(media, 'document', None):
        doc = media.document
        mime_type = getattr(doc, 'mime_type', '') or ''
        if mime_type.startswith('video/'):
            media_type = 'video'
        elif mime_type.startswith('audio/'):
            media_type = 'audio'
        else:
            media_type = 'document'
        return doc.id, doc.access_hash, media_type
    return None


class MessageProcessor:
    """Обрабатывает одно сообщение: юзер, медиа, словарь для save_message."""

    def __init__(self, api_client, db_path: str, max_media_size_bytes: Optional[int] = None):
        self.api_client = api_client
        self.db_path = db_path
        self.max_media_size_bytes = max_media_size_bytes
        self._users_seen = set()   # telegram_id, уже обработанные за этот запуск

    # --- пользователи ------------------------------------------------------

    async def ensure_user(self, conn, message: Message, verbose: bool = False):
        """Сохраняет отправителя, по возможности без лишних запросов к API.

        ``message.sender`` уже развёрнут Telethon'ом при получении сообщений —
        отдельный ``get_entity`` нужен только когда там None.
        """
        user_id = message.sender_id or 0
        if user_id == 0:
            save_user(conn, SYSTEM_USER, commit=False)
            return
        if user_id in self._users_seen:
            return
        self._users_seen.add(user_id)

        sender = getattr(message, 'sender', None)
        if sender is not None and getattr(sender, 'id', None):
            save_user(conn, self.api_client.user_to_dict(sender), commit=False)
            return
        if get_user(conn, user_id):
            return
        info = await self.api_client.get_user_info(user_id)
        save_user(conn, info, commit=False)
        if verbose:
            print(f"    [USER] {user_id}: {info.get('first_name')} @{info.get('username')}")

    # --- медиа -------------------------------------------------------------

    async def download_media(self, conn, message: Message, media_dir: str,
                             topic_id: Optional[int] = None,
                             verbose: bool = False) -> Optional[str]:
        """Скачивает медиа (если ещё не скачано) и возвращает путь к файлу."""
        info = media_info(message)
        if not info:
            return None
        media_id, access_hash, _ = info

        # Лимит размера: в форум-группах попадаются многогигабайтные архивы,
        # которые не нужны на веб-архиве и забивают диск.
        file_size = getattr(getattr(message, 'file', None), 'size', None)
        if self.max_media_size_bytes and file_size and file_size > self.max_media_size_bytes:
            name = getattr(getattr(message, 'file', None), 'name', None) or ''
            print(f"    [SKIP] msg.id={message.id}: {human_readable_size(file_size)} "
                  f"больше лимита {human_readable_size(self.max_media_size_bytes)} {name!r}")
            return None

        existing_path = get_file_path_by_media_info(conn, media_id, access_hash)
        if existing_path and os.path.exists(existing_path):
            if get_file_size_by_path(conn, existing_path) is None:
                save_media_file_info(conn, media_id, access_hash, existing_path,
                                     os.path.getsize(existing_path), commit=False)
            if verbose:
                print(f"    [CACHE] media_id={media_id} -> {existing_path}")
            return existing_path

        sub_dir = f"topics/{topic_id}" if topic_id else "global"
        save_dir = os.path.join(media_dir, sub_dir)
        os.makedirs(save_dir, exist_ok=True)

        # Имя файла зависит от id сообщения: телеграмные имена (sticker.webm,
        # photo_..._(1).jpg) в одной папке перетирают друг друга.
        default_name = f"{message.id}"
        file_obj = getattr(message, 'file', None)
        ext = getattr(file_obj, 'ext', None) or ''
        original_name = getattr(file_obj, 'name', None)
        if original_name:
            filename = _safe_filename(original_name, default_name + ext)
            filename = f"{message.id}_{filename}"
            if ext and not filename.lower().endswith(ext.lower()):
                filename += ext
        else:
            filename = f"{default_name}{ext}"
        target = os.path.join(save_dir, filename)

        delay = 2
        file_path = None
        for attempt in range(1, 4):
            try:
                file_path = await message.download_media(file=target)
                break
            except Exception as e:
                if attempt == 3:
                    # Недокачанный файл не оставляем: он попадёт в output и
                    # сломает превью («cannot identify image file»).
                    if os.path.exists(target):
                        os.remove(target)
                    print(f"[!] Не удалось скачать медиа msg.id={message.id}: {e}")
                    return None
                print(f"[!] Ошибка скачивания msg.id={message.id} ({e}), повтор через {delay} с")
                await asyncio.sleep(delay)
                delay *= 2
        else:
            return None

        if not file_path or not os.path.exists(file_path):
            print(f"[!] Файл не появился на диске: msg.id={message.id}")
            return None

        size = os.path.getsize(file_path)
        save_media_file_info(conn, media_id, access_hash, file_path, size, commit=False)
        if verbose:
            print(f"    [DOWNLOAD] msg.id={message.id} -> {file_path} ({human_readable_size(size)})")
        return file_path

    # --- сообщение ---------------------------------------------------------

    def message_to_dict(self, msg: Message, topic_id: Optional[int] = None) -> Dict[str, Any]:
        """Готовит запись для save_message (без медиа-полей)."""
        poll_data = None
        if getattr(msg, 'poll', None):
            poll = msg.poll.poll
            poll_data = json.dumps({
                'question': poll.question,
                'answers': [{'text': a.text, 'votes': a.voters} for a in poll.answers],
                'total_voters': poll.total_voters,
            }, ensure_ascii=False)

        return {
            'telegram_id': msg.id,
            'topic_id': topic_id or 0,
            'user_id': msg.sender_id or 0,
            'text': msg.text or '',
            'timestamp': msg.date.isoformat(),
            'reply_to_msg_id': self._reply_to_id(msg, topic_id),
            'media_type': None,
            'media_path': None,
            'media_skipped_size': None,
            'poll_data': poll_data,
            'file_extension': None,
        }

    def skipped_size(self, message: Message) -> Optional[int]:
        """Размер вложения, которое не будет скачано из-за лимита (или None)."""
        if not self.max_media_size_bytes:
            return None
        size = getattr(getattr(message, 'file', None), 'size', None)
        if size and size > self.max_media_size_bytes:
            return size
        return None

    @staticmethod
    def _reply_to_id(msg: Message, topic_id: Optional[int]) -> Optional[int]:
        """id сообщения, на которое отвечают.

        В форуме корневые сообщения топика имеют reply_to_msg_id == topic_id —
        это не ответ, а служебная привязка к теме.
        """
        reply = getattr(msg, 'reply_to', None)
        if not reply:
            return None
        reply_id = getattr(reply, 'reply_to_msg_id', None)
        if not reply_id or reply_id == topic_id:
            return None
        return reply_id
