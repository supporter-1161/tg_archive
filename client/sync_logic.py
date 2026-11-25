# client/sync_logic.py
"""Логика синхронизации тем и сообщений.

Семантика Telethon (см. references/telethon-sync.md в скилле):

* ``reverse=False`` — итерация от новых к старым, ``offset_id`` = верхняя
  граница выборки, следующая страница = минимальный id пачки;
* ``reverse=True``  — итерация от старых к новым, ``offset_id`` = нижняя
  граница, следующая страница = максимальный id пачки.

Отсюда два режима:

* ``forward``  — только новое: идём от самых новых вниз, пока не упрёмся в
  ``last_message_id`` темы;
* ``backward`` — полный проход по истории от старых к новым, уже сохранённые
  id пропускаются. Так заполняются дыры, которые мог оставить старый код.
"""
import asyncio
import os
import random

from database import (
    get_db_connection,
    get_known_message_ids,
    get_last_message_id,
    save_message,
    save_topic,
    update_last_message_id,
)
from client.message_processor import media_info


class SyncLogic:
    def __init__(self, api_client, message_processor, batch_size: int = 100,
                 sleep_range=(0.5, 1.5)):
        self.api_client = api_client
        self.message_processor = message_processor
        self.batch_size = batch_size
        self.sleep_range = sleep_range

    # --- точка входа -------------------------------------------------------

    async def sync_topics_and_messages(self, db_path: str, media_dir: str,
                                       verbose: bool = False, topic_ids: list = None,
                                       sync_direction: str = 'forward'):
        conn = get_db_connection(db_path)
        try:
            topics = await self.api_client.get_topics()
            print(f"[+] Найдено тем: {len(topics)}")
            if topic_ids:
                topics = [t for t in topics if t['telegram_id'] in topic_ids]
                print(f"[+] Отфильтровано до {len(topics)} тем: {topic_ids}")
            if not topics:
                print("[!] Нечего синхронизировать")
                return

            total_saved = 0
            for topic in topics:
                save_topic(conn, topic)
                conn.commit()
                topic_id = topic['telegram_id']
                if sync_direction == 'backward':
                    saved = await self._sync_full_history(conn, topic, media_dir, verbose)
                else:
                    saved = await self._sync_new(conn, topic, media_dir, verbose)
                total_saved += saved
                print(f"[+] Тема {topic_id} «{topic['title']}»: сохранено {saved}")
            print(f"[+] Синхронизация завершена, всего сохранено сообщений: {total_saved}")
        finally:
            conn.close()

    # --- режимы ------------------------------------------------------------

    async def _sync_new(self, conn, topic, media_dir: str, verbose: bool) -> int:
        """Только сообщения новее last_message_id (по умолчанию — вперед)."""
        topic_id = topic['telegram_id']
        threshold = get_last_message_id(conn, topic_id) or 0
        max_seen = threshold
        offset_id = 0
        saved = 0
        print(f"[*] Тема [{topic_id}] {topic['title']}: forward, начиная после {threshold}")

        while True:
            messages = await self.api_client.get_messages(
                topic_id=topic_id, offset_id=offset_id, limit=self.batch_size, reverse=False
            )
            if not messages:
                break
            messages.sort(key=lambda m: m.id, reverse=True)
            if verbose:
                print(f"  [BATCH:{topic_id}] {len(messages)} сообщений, "
                      f"id {messages[-1].id}..{messages[0].id}")

            reached_known = False
            since_commit = 0
            for msg in messages:
                if msg.id <= threshold:
                    reached_known = True
                    break
                if await self._process_message(conn, msg, topic_id, media_dir, verbose):
                    saved += 1
                since_commit += 1
                if since_commit >= 20:
                    # Фиксируем прогресс, но last_message_id не двигаем: иначе
                    # после обрыва forward посчитает оставшуюся часть пачки
                    # уже известной и пропустит её.
                    conn.commit()
                    since_commit = 0
            # Пачка отсортирована по убыванию: messages[0] — самый новый id.
            if messages and messages[0].id > max_seen:
                max_seen = messages[0].id
                update_last_message_id(conn, topic_id, max_seen, commit=False)
            conn.commit()
            if not verbose:
                print(f"  [~] тема {topic_id}: +{saved}, пачка id {messages[-1].id}..{messages[0].id}")

            if reached_known or len(messages) < self.batch_size:
                break
            offset_id = min(m.id for m in messages)
            await self._pause()
        return saved

    async def _sync_full_history(self, conn, topic, media_dir: str, verbose: bool) -> int:
        """Полный проход от старых к новым, сохранённое пропускаем."""
        topic_id = topic['telegram_id']
        offset_id = 0
        saved = 0
        max_saved = get_last_message_id(conn, topic_id) or 0
        print(f"[*] Тема [{topic_id}] {topic['title']}: backward, полная история")

        while True:
            messages = await self.api_client.get_messages(
                topic_id=topic_id, offset_id=offset_id, limit=self.batch_size, reverse=True
            )
            if not messages:
                break
            ids = [m.id for m in messages]
            known = get_known_message_ids(conn, topic_id, min(ids), max(ids))
            if verbose:
                print(f"  [BATCH:{topic_id}] {len(messages)} сообщений, "
                      f"id {min(ids)}..{max(ids)}, уже в базе: {len(known)}")

            for msg in sorted(messages, key=lambda m: m.id):
                if msg.id in known:
                    continue
                if await self._process_message(conn, msg, topic_id, media_dir, verbose):
                    saved += 1
                max_saved = max(max_saved, msg.id)
                if saved and saved % 20 == 0:
                    conn.commit()
            update_last_message_id(conn, topic_id, max_saved, commit=False)
            conn.commit()
            if not verbose:
                print(f"  [~] тема {topic_id}: +{saved}, пачка id {min(ids)}..{max(ids)}")

            if len(messages) < self.batch_size:
                break
            offset_id = max(ids)
            await self._pause()
        return saved

    # --- обработка одного сообщения ---------------------------------------

    async def _process_message(self, conn, msg, topic_id: int, media_dir: str,
                               verbose: bool) -> bool:
        if getattr(msg, 'action', None) is not None:
            # Служебные сообщения (вход/выход, закрепление) в архиве не нужны.
            if verbose:
                print(f"    [SKIP] служебное сообщение {msg.id}")
            return False

        await self.message_processor.ensure_user(conn, msg, verbose=verbose)
        media_path = await self.message_processor.download_media(
            conn, msg, media_dir, topic_id, verbose=verbose
        )
        data = self.message_processor.message_to_dict(msg, topic_id)
        if media_path:
            info = media_info(msg)
            data['media_type'] = info[2] if info else None
            data['media_path'] = media_path
            ext = os.path.splitext(media_path)[1].lstrip('.').lower()
            data['file_extension'] = ext or None
        else:
            skipped = self.message_processor.skipped_size(msg)
            if skipped:
                info = media_info(msg)
                data['media_type'] = info[2] if info else None
                data['media_skipped_size'] = skipped
                ext = (getattr(getattr(msg, 'file', None), 'ext', None) or '').lstrip('.').lower()
                data['file_extension'] = ext or None

        save_message(conn, data, commit=False)
        if verbose:
            print(f"    [SAVE] {msg.id}")
        return True

    async def _pause(self):
        await asyncio.sleep(random.uniform(*self.sleep_range))
