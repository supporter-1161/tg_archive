# client/sync_logic.py
from database import get_db_connection, save_topic, get_last_message_id, update_last_message_id, save_message
import time
import random
import asyncio
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
import os

class SyncLogic:
    """
    Класс для логики синхронизации тем и сообщений.
    Использует TelegramAPIClient для получения данных и MessageProcessor для их обработки.
    """
    def __init__(self, api_client, message_processor):
        self.api_client = api_client
        self.message_processor = message_processor

    async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None, sync_direction: str = 'forward'):
        """Синхронизирует темы и сообщения."""
        conn = get_db_connection(db_path)
        # Получаем темы через api_client
        topics = await self.api_client.get_topics()
        print(f"[+] Найдено тем: {len(topics)}")
        # Фильтруем по ID, если указаны
        if topic_ids:
            topics = [t for t in topics if t['telegram_id'] in topic_ids]
            print(f"[+] Отфильтровано до {len(topics)} тем: {topic_ids}")
        # Сохраняем темы в БД
        for topic in topics:
            topic_id = topic['telegram_id']
            save_topic(conn, topic)
            last_msg_id = get_last_message_id(conn, topic_id) or 0
            initial_last_msg_id = last_msg_id # <-- Сохраняем начальное значение last_msg_id
            # --- ЛОГИКА offset_id И ЦИКЛА В ЗАВИСИМОСТИ ОТ НАПРАВЛЕНИЯ ---
            if sync_direction == 'forward':
                # Для "forward" (поиск новых сообщений) используем логику backward,
                # но останавливаемся, когда достигаем initial_last_msg_id.
                # reverse=True, offset_id=0 (или не указываем, начинаем с самых новых)
                offset_id = 0 # Начинаем с самых новых
                reached_known = False # Флаг для остановки
                print(f"[*] Обработка темы: [{topic_id}] {topic['title']} (forward, offset: {offset_id}, initial_last_msg_id: {initial_last_msg_id})")
                while not reached_known: # <-- Внешний цикл с проверкой reached_known
                    # Получаем сообщения *в обратном хронологическом порядке*, начиная с offset_id (0)
                    # reverse=True (установлено в get_messages)
                    messages = await self.api_client.get_messages(topic_id=topic_id, offset_id=offset_id, limit=100, reverse=True)
                    if verbose:
                        print(f"  [DEBUG:{topic_id}] Получено {len(messages)} сообщений (offset_id={offset_id})")
                    if not messages:
                        if verbose:
                            print(f"  [DEBUG:{topic_id}] Нет новых сообщений, выходим из цикла")
                        break
                    # Логируем ID сообщений
                    if verbose:
                        # При reverse=True сообщения идут от новых к старым.
                        # Сортировка по убыванию ID для понятности.
                        msg_ids = sorted([msg.id for msg in messages], reverse=True) # От новых к старых
                        print(f"  [DEBUG:{topic_id}] IDs сообщений (reverse): {msg_ids[:10]}{'...' if len(msg_ids) > 10 else ''}")
                    # Сообщения приходят от новых к старым, отсортируем для корректной обработки и обновления offset_id
                    # Это уже отсортировано reverse=True, но перестрахуемся.
                    messages = sorted(messages, key=lambda m: m.id, reverse=True) # От новых к старых
                    for msg in messages:
                        if verbose:
                            print(f"    [DEBUG:{topic_id}] Обработка msg.id={msg.id}, initial_last_msg_id={initial_last_msg_id}")
                        if msg.id <= initial_last_msg_id: # <-- Сравниваем с initial_last_msg_id!
                            if verbose:
                                print(f"      [REACHED_KNOWN:{topic_id}] Достигли или прошли мимо начального last_msg_id (msg.id={msg.id} <= initial_last_msg_id={initial_last_msg_id}), выходим из цикла по сообщениям в пачке")
                            reached_known = True # <-- Устанавливаем флаг
                            break # <-- Выходим из цикла for msg in messages
                        # Обработка пользователя (теперь через MessageProcessor)
                        await self.message_processor.process_user(conn, msg.sender_id)
                        # Скачивание медиа (теперь через MessageProcessor)
                        media_path = await self.message_processor.download_media(msg, media_dir, topic_id)
                        # Подготовка данных для сохранения (теперь через MessageProcessor)
                        msg_dict = self.message_processor.message_to_dict(msg, topic_id)
                        msg_dict['media_path'] = media_path

                        if media_path:
                            _, ext = os.path.splitext(media_path)
                            file_extension = ext[1:] # Сохраняем реальное расширение файла
                            # Определяем тип медиа для CHECK-констрейнта в БД
                            determined_media_type = None
                            if msg.media: # Проверяем, было ли медиа вообще
                                if isinstance(msg.media, MessageMediaPhoto):
                                    determined_media_type = 'photo'
                                elif isinstance(msg.media, MessageMediaDocument):
                                    mime_type = getattr(msg.media.document, 'mime_type', '')
                                    if 'video' in mime_type:
                                        determined_media_type = 'video'
                                    elif 'audio' in mime_type:
                                        determined_media_type = 'audio'
                                    else:
                                        determined_media_type = 'document' # Для остальных документов
                            msg_dict['media_type'] = determined_media_type
                            msg_dict['file_extension'] = file_extension

                        save_message(conn, msg_dict) # Теперь save_message должен быть обновлён для принятия file_extension
                        if verbose:
                            print(f"      [SAVE:{topic_id}] Сохранено сообщение {msg.id}")
                        # Обновляем last_message_id
                        if msg.id > last_msg_id:
                            last_msg_id = msg.id # <-- Обновляем локальную переменную
                            update_last_message_id(conn, topic_id, last_msg_id) # <-- Обновляем в БД
                            if verbose:
                                print(f"      [UPDATE:{topic_id}] last_msg_id обновлён до {last_msg_id}")
                    # Проверяем флаг reached_known перед обновлением offset_id
                    if reached_known:
                        break # <-- Выходим из внешнего цикла while
                    # Смещаем offset для следующей пачки.
                    # При reverse=True: offset_id должен быть минимальным ID в текущей пачке, чтобы следующий запрос начался до него.
                    # Так как мы отсортировали по убыванию, последний элемент — с минимальным ID.
                    if messages:
                        offset_id = messages[-1].id  # <-- min
                        if verbose:
                            print(f"      [OFFSET:{topic_id}] offset_id обновлён до {offset_id}")
                    else:
                        # Защита от зависания, хотя вряд ли сработает
                        break
                    # Задержка между запросами (0.5–1.5 секунды)
                    delay = random.uniform(0.5, 1.5)
                    if verbose:
                        print(f"      [SLEEP:{topic_id}] Задержка {delay:.2f} секунд...")
                    time.sleep(delay)
                if verbose:
                    print(f"  [DONE:{topic_id}] Обработка темы (forward) завершена, достигнуто известное сообщение или конец темы.")
            elif sync_direction == 'backward':
                # Старая логика, начинаем с 0 (или last_msg_id, если нужно досинхронизировать до него)
                # reverse=True, offset_id=0 (или last_msg_id)
                offset_id = 0 # или last_msg_id, если нужно начать с определённого места и идти к началу темы
                print(f"[*] Обработка темы: [{topic_id}] {topic['title']} (backward, offset: {offset_id}, last_msg_id: {last_msg_id})")
                while True:
                    # Получаем сообщения *в обратном хронологическом порядке*, начиная с offset_id (или с самых новых, если offset_id=0)
                    # reverse=True (установлено в get_messages, если sync_direction == 'backward')
                    messages = await self.api_client.get_messages(topic_id=topic_id, offset_id=offset_id, limit=100, reverse=True)
                    if verbose:
                        print(f"  [DEBUG:{topic_id}] Получено {len(messages)} сообщений (offset_id={offset_id})")
                    if not messages:
                        if verbose:
                            print(f"  [DEBUG:{topic_id}] Нет (старых) сообщений, выходим из цикла")
                        break
                    # Логируем ID сообщений
                    if verbose:
                        # При reverse=True сообщения идут от новых к старым.
                        # Сортировка по возрастанию ID для понятности.
                        msg_ids = sorted([msg.id for msg in messages], reverse=True) # От новых к старых
                        print(f"  [DEBUG:{topic_id}] IDs сообщений (reverse): {msg_ids[:10]}{'...' if len(msg_ids) > 10 else ''}")
                    # Сообщения приходят от новых к старым, отсортируем для корректной обработки и обновления offset_id
                    messages = sorted(messages, key=lambda m: m.id, reverse=True) # От новых к старых
                    for msg in messages:
                        if verbose:
                            print(f"    [DEBUG:{topic_id}] Обработка msg.id={msg.id}, last_msg_id={last_msg_id}")
                        if msg.id <= last_msg_id:
                            if verbose:
                                print(f"      [SKIP:{topic_id}] Пропускаем (уже есть, msg.id <= last_msg_id)")
                            continue  # Пропускаем уже сохранённые
                        # Обработка пользователя (теперь через MessageProcessor)
                        await self.message_processor.process_user(conn, msg.sender_id)
                        # Скачивание медиа (теперь через MessageProcessor)
                        media_path = await self.message_processor.download_media(msg, media_dir, topic_id)
                        # Подготовка данных для сохранения (теперь через MessageProcessor)
                        msg_dict = self.message_processor.message_to_dict(msg, topic_id)
                        msg_dict['media_path'] = media_path

                        if media_path:
                            _, ext = os.path.splitext(media_path)
                            file_extension = ext[1:] # Сохраняем реальное расширение файла
                            # Определяем тип медиа для CHECK-констрейнта в БД
                            determined_media_type = None
                            if msg.media: # Проверяем, было ли медиа вообще
                                if isinstance(msg.media, MessageMediaPhoto):
                                    determined_media_type = 'photo'
                                elif isinstance(msg.media, MessageMediaDocument):
                                    mime_type = getattr(msg.media.document, 'mime_type', '')
                                    if 'video' in mime_type:
                                        determined_media_type = 'video'
                                    elif 'audio' in mime_type:
                                        determined_media_type = 'audio'
                                    else:
                                        determined_media_type = 'document' # Для остальных документов
                            msg_dict['media_type'] = determined_media_type
                            msg_dict['file_extension'] = file_extension

                        save_message(conn, msg_dict) # Теперь save_message должен быть обновлён для принятия file_extension
                        if verbose:
                            print(f"      [SAVE:{topic_id}] Сохранено сообщение {msg.id}")
                        # Обновляем last_message_id
                        if msg.id > last_msg_id:
                            last_msg_id = msg.id
                            update_last_message_id(conn, topic_id, last_msg_id)
                            if verbose:
                                print(f"      [UPDATE:{topic_id}] last_msg_id обновлён до {last_msg_id}")
                    # Смещаем offset для следующей пачки.
                    # При reverse=True: offset_id должен быть минимальным ID в текущей пачке, чтобы следующий запрос начался до него.
                    # Так как мы отсортировали по убыванию, последний элемент — с минимальным ID.
                    if messages:
                        offset_id = messages[-1].id  # <-- min
                        if verbose:
                            print(f"      [OFFSET:{topic_id}] offset_id обновлён до {offset_id}")
                    else:
                        # Защита от зависания, хотя вряд ли сработает
                        break
                    # Задержка между запросами (0.5–1.5 секунды)
                    delay = random.uniform(0.5, 1.5)
                    if verbose:
                        print(f"      [SLEEP:{topic_id}] Задержка {delay:.2f} секунд...")
                    time.sleep(delay)
                if verbose:
                    print(f"  [DONE:{topic_id}] Обработка темы (backward) завершена, достигнут конец темы или offset.")
        conn.close()
        print("[+] Синхронизация завершена")
