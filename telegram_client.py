# telegram_client.py

from telethon import TelegramClient
from telethon.tl.types import PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument
from telethon.tl.functions.channels import GetForumTopicsRequest
import os
import asyncio
from typing import List, Dict, Any, Optional
import json
# --- ИМПОРТЫ (включая новые функции для работы с media_files и file_extension) ---
from database import get_db_connection, save_topic, get_last_message_id, update_last_message_id, save_user, save_message, get_file_path_by_media_info, save_media_file_info
# --- КОНЕЦ ИМПОРТОВ ---
import time
import random

class TelegramArchiver:
    # --- ИЗМЕНЕНИЕ __init__ (добавлен sync_direction) ---
    def __init__(self, api_id: str, api_hash: str, session_name: str, group_id: int, sync_direction: str = 'forward'):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_name = session_name
        self.group_id = group_id
        # Сохраняем направление синхронизации
        self.sync_direction = sync_direction

        # Реалистичные параметры для обхода защиты
        self.client = TelegramClient(
            session=session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            app_version='10.4.2',
            device_model='SM-G991B',
            system_version='14'
        )
    # --- КОНЕЦ ИЗМЕНЕНИЯ __init__ ---

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
            print(f"[DEBUG] Topic ID: {topic.id}, Title: '{topic.title}', Icon Emoji Attr: {hasattr(topic, 'icon_emoji')}, Icon Emoji Value: {getattr(topic, 'icon_emoji', 'ATTR_NOT_FOUND')}, Type: {type(getattr(topic, 'icon_emoji', 'ATTR_NOT_FOUND'))}")

            topics.append({
                'telegram_id': topic.id,
                'title': topic.title,
                #'icon_emoji': topic.icon_emoji if hasattr(topic, 'icon_emoji') else None,
                'icon_emoji': getattr(topic, 'icon_emoji', None), # <-- Новая строка: getattr безопасно возвращает значение или None
                'is_closed': getattr(topic, 'closed', False),
                'created_at': getattr(topic, 'date', None)
            })
        return topics

    # --- ИЗМЕНЕНИЕ get_messages (учёт sync_direction) ---
    # Убран параметр reverse из сигнатуры, он будет определяться внутри
    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0, limit: int = 100, reverse: Optional[bool] = None) -> List[Message]:
        """Получает сообщения из темы или из общего чата."""
        # Если reverse не передан, определяем по self.sync_direction
        if reverse is None:
            reverse = (self.sync_direction == 'backward')
        # ---
        if topic_id:
            # Фильтр по теме
            messages = await self.client.get_messages(
                PeerChannel(channel_id=abs(self.group_id)),
                limit=limit,
                offset_id=offset_id,
                filter=None,
                reply_to=topic_id,
                reverse=reverse # <-- Используем вычисленное значение reverse
            )
        else:
            # Глобальные сообщения (без тем)
            messages = await self.client.get_messages(
                PeerChannel(channel_id=abs(self.group_id)),
                limit=limit,
                offset_id=offset_id,
                filter=None,
                reverse=reverse # <-- Используем вычисленное значение reverse
            )
        return messages
    # --- КОНЕЦ ИЗМЕНЕНИЯ get_messages ---

    # --- ИЗМЕНЕНИЕ download_media (принимает db_path) ---
    async def download_media(self, message: Message, media_dir: str, topic_id: Optional[int] = None, db_path: str = None) -> Optional[str]:
        """Скачивает медиа из сообщения, избегая дубликатов, и возвращает путь."""
        if not message.media or not db_path: # Проверяем db_path
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
            # Старая логика определения типа для возврата
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
            # Если у объекта нет id/access_hash, мы не можем проверить дубликат
            # Возвращаем None, чтобы избежать скачивания, или продолжить старую логику
            # Для простоты, если нет id/access_hash, будем считать, что это уникальный файл
            # и продолжим старую логику скачивания.
            # Это крайний случай, обычно у медиа есть id/access_hash.
            # Или можно попробовать скачать и сохранить с хэшем содержимого, но это сложнее.
            # Пока оставим так, как было, но с предупреждением.
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


        # --- ПРОВЕРКА НА СУЩЕСТВОВАНИЕ В БД (основная логика) ---
        conn = get_db_connection(db_path) # <-- Используем переданный db_path
        existing_path = get_file_path_by_media_info(conn, media_id, access_hash)
        conn.close()

        if existing_path:
            # Файл уже был скачан, используем существующий путь
            if os.path.exists(existing_path): # Проверяем, не был ли файл удалён вручную
                print(f"    [CACHE:{topic_id}] Используем кэшированный файл для media_id={media_id}")
                return existing_path
            else:
                # Путь существует в БД, но файл отсутствует на диске.
                # В идеале, нужно удалить запись из media_files, но для простоты пока просто скачаем заново.
                # Это может привести к ситуации, где файл не скачается, но в БД останется путь к несуществующему файлу.
                # Это не критично, но можно улучшить.
                print(f"    [CACHE:{topic_id}] Кэшированный файл не найден на диске: {existing_path}. Скачиваем заново.")
                # Продолжаем скачивание

        # --- ОПРЕДЕЛЕНИЕ ТИПА МЕДИА (для подкаталогов, если нужно) ---
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
                # Telethon сам генерирует имя файла, но может добавить суффиксы при конфликте.
                # Нам нужно имя файла, которое он выбрал.
                file_path = await message.download_media(file=save_dir)
                if file_path: # Если скачивание прошло успешно
                    # --- СОХРАНЕНИЕ ИНФОРМАЦИИ О ФАЙЛЕ В БД ---
                    conn = get_db_connection(db_path) # <-- Используем переданный db_path
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
    # ---

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

    # --- ИЗМЕНЕНИЕ sync_topics_and_messages (учёт sync_direction и исправленная логика) ---
    # --- ИЗМЕНЕНИЕ sync_topics_and_messages (учёт sync_direction и исправленная логика) ---
    # Принимает sync_direction
    async def sync_topics_and_messages(self, db_path: str, media_dir: str, verbose: bool = False, topic_ids: list = None, sync_direction: str = 'forward'):
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
                    messages = await self.get_messages(topic_id=topic_id, offset_id=offset_id, limit=100, reverse=True)
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
                        msg_ids = sorted([msg.id for msg in messages], reverse=True) # От новых к старым
                        print(f"  [DEBUG:{topic_id}] IDs сообщений (reverse): {msg_ids[:10]}{'...' if len(msg_ids) > 10 else ''}")

                    # Сообщения приходят от новых к старым, отсортируем для корректной обработки и обновления offset_id
                    # Это уже отсортировано reverse=True, но перестрахуемся.
                    messages = sorted(messages, key=lambda m: m.id, reverse=True) # От новых к старым

                    for msg in messages:
                        if verbose:
                            print(f"    [DEBUG:{topic_id}] Обработка msg.id={msg.id}, initial_last_msg_id={initial_last_msg_id}")
                        if msg.id <= initial_last_msg_id: # <-- Сравниваем с initial_last_msg_id!
                            if verbose:
                                print(f"      [REACHED_KNOWN:{topic_id}] Достигли или прошли мимо начального last_msg_id (msg.id={msg.id} <= initial_last_msg_id={initial_last_msg_id}), выходим из цикла по сообщениям в пачке")
                            reached_known = True # <-- Устанавливаем флаг
                            break # <-- Выходим из цикла for msg in messages
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
                        media_path = await self.download_media(msg, media_dir, topic_id, db_path) # <-- Убедимся, что db_path передаётся
                        # Подготовка данных для сохранения
                        msg_dict = self.message_to_dict(msg, topic_id)
                        msg_dict['media_path'] = media_path
                        # --- НОВАЯ ЛОГИКА (для forward та же, что и для backward) ---
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
                        # --- КОНЕЦ НОВОЙ ЛОГИКИ ---
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
                # offset_id указывает на *следующее* сообщение, с которого начать.
                # reverse=True означает: получить сообщения *до* offset_id, в обратном порядке.
                # Если offset_id=0, то получить последние (новые) сообщения, в обратном порядке.
                offset_id = 0 # или last_msg_id, если нужно начать с определённого места и идти к началу темы
                print(f"[*] Обработка темы: [{topic_id}] {topic['title']} (backward, offset: {offset_id}, last_msg_id: {last_msg_id})")
                while True:
                    # Получаем сообщения *в обратном хронологическом порядке*, начиная с offset_id (или с самых новых, если offset_id=0)
                    # reverse=True (установлено в get_messages, если sync_direction == 'backward')
                    messages = await self.get_messages(topic_id=topic_id, offset_id=offset_id, limit=100, reverse=True)
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
                        msg_ids = sorted([msg.id for msg in messages], reverse=True) # От новых к старым
                        print(f"  [DEBUG:{topic_id}] IDs сообщений (reverse): {msg_ids[:10]}{'...' if len(msg_ids) > 10 else ''}")

                    # Сообщения приходят от новых к старым, отсортируем для корректной обработки и обновления offset_id
                    messages = sorted(messages, key=lambda m: m.id, reverse=True) # От новых к старым

                    for msg in messages:
                        if verbose:
                            print(f"    [DEBUG:{topic_id}] Обработка msg.id={msg.id}, last_msg_id={last_msg_id}")
                        if msg.id <= last_msg_id:
                            if verbose:
                                print(f"      [SKIP:{topic_id}] Пропускаем (уже есть, msg.id <= last_msg_id)")
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
                        media_path = await self.download_media(msg, media_dir, topic_id, db_path) # <-- Убедимся, что db_path передаётся
                        # Подготовка данных для сохранения
                        msg_dict = self.message_to_dict(msg, topic_id)
                        msg_dict['media_path'] = media_path
                        # --- НОВАЯ ЛОГИКА (для backward та же, что и для forward) ---
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
                        # --- КОНЕЦ НОВОЙ ЛОГИКИ ---
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
    # --- КОНЕЦ ИЗМЕНЕНИЯ sync_topics_and_messages ---
   # --- КОНЕЦ ИЗМЕНЕНИЯ sync_topics_and_messages ---


    async def close(self):
        """Закрывает клиент."""
        await self.client.disconnect()

