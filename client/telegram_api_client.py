# client/telegram_api_client.py
"""Тонкая обёртка над Telethon: только запросы к Telegram + ретраи.

Здесь нет логики архивации — она в sync_logic/message_processor.
"""
import asyncio
import inspect
from typing import List, Dict, Any, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.types import PeerChannel, Message

# Telethon 1.42 переименовал аргумент GetForumTopicsRequest: channel -> peer.
# Поддерживаем обе версии, чтобы не зависеть от установленного пакета.
_TOPIC_ARG = 'peer' if 'peer' in inspect.signature(
    GetForumTopicsRequest.__init__).parameters else 'channel'


class SessionNotAuthorized(RuntimeError):
    """Сессия есть, но вход в аккаунт не выполнен."""


class TelegramAPIClient:
    def __init__(self, api_id: str, api_hash: str, session_name: str, group_id: int,
                 request_retries: int = 3):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_name = session_name
        self.group_id = group_id
        self.request_retries = request_retries
        self.client = TelegramClient(
            session=session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            app_version='10.4.2',
            device_model='SM-G991B',
            system_version='14',
        )
        self._started = False

    # --- служебное ---------------------------------------------------------

    @property
    def peer(self) -> PeerChannel:
        """Пир «как в конфиге» — только для совместимости."""
        return PeerChannel(channel_id=abs(self.group_id))

    async def _resolve_peer(self):
        """Резолвит группу в InputPeer (с access_hash).

        Просто PeerChannel(id) недостаточно: методы вроде GetForumTopics
        требуют access_hash, иначе ChannelInvalidError. В конфиге id бывает
        в «сыром» виде (-2723522097) без префикса -100, поэтому пробуем
        несколько вариантов.
        """
        gid = int(self.group_id)
        candidates = [gid]
        if not str(gid).startswith('-100'):
            candidates.append(int(f'-100{abs(gid)}'))
        candidates.append(abs(gid))

        last_error = None
        for candidate in candidates:
            try:
                entity = await self.client.get_entity(candidate)
            except Exception as e:  # ChatIdInvalidError, ValueError и т.п.
                last_error = e
                continue
            if getattr(entity, 'id', None) is None:
                continue
            try:
                peer = await self.client.get_input_entity(entity)
            except Exception as e:
                last_error = e
                continue
            title = getattr(entity, 'title', None) or getattr(entity, 'first_name', '')
            print(f"[+] Группа: «{title}» (id={entity.id}, forum={getattr(entity, 'forum', None)})")
            return peer
        raise RuntimeError(f"Не удалось определить группу {gid}: {last_error}")

    async def _call(self, factory):
        """Выполняет запрос с ретраями на FloodWait и сетевые ошибки."""
        for attempt in range(1, self.request_retries + 1):
            try:
                return await factory()
            except FloodWaitError as e:
                wait = e.seconds + 1
                print(f"[!] FloodWait: ждём {wait} с (попытка {attempt}/{self.request_retries})")
                await asyncio.sleep(wait)
            except (TimeoutError, ConnectionError, OSError) as e:
                if attempt == self.request_retries:
                    raise
                wait = 2 * attempt
                print(f"[!] Сетевая ошибка ({e}), повтор через {wait} с")
                await asyncio.sleep(wait)
            except RPCError as e:
                # Часть ошибок Telegram транзиентна (RPC_CALL_FAIL, -503 и т.п.)
                if attempt == self.request_retries:
                    raise
                wait = 3 * attempt
                print(f"[!] RPCError: {e}, повтор через {wait} с")
                await asyncio.sleep(wait)

    # --- подключение -------------------------------------------------------

    async def start(self):
        """Подключается и проверяет, что сессия авторизована.

        Не вызываем ``client.start()``: на неавторизованной сессии он уходит в
        интерактивный ввод телефона и падает с EOF в неинтерактивном запуске.
        """
        if self._started:
            return
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            raise SessionNotAuthorized(
                "Telegram-сессия не авторизована. Выполните один раз интерактивно: "
                "`python tg_archive.py login --config config.yaml`"
            )
        self._started = True
        self._input_peer = await self._resolve_peer()
        print("[+] Telegram API клиент запущен")

    async def login(self, phone: Optional[str] = None):
        """Интерактивный вход (код/2FA спросит сам Telethon)."""
        await self.client.start(phone=phone or (lambda: input('Телефон (или bot token): ')))
        me = await self.client.get_me()
        print(f"[+] Вход выполнен: {me.first_name} (@{me.username}) id={me.id}")

    async def close(self):
        if self._started:
            await self.client.disconnect()
            self._started = False

    # --- данные ------------------------------------------------------------

    async def get_topics(self) -> List[Dict[str, Any]]:
        """Все темы форума (с пагинацией по offset_topic)."""
        self._check_started()
        topics: List[Dict[str, Any]] = []
        offset_topic = 0
        while True:
            result = await self._call(lambda: self.client(GetForumTopicsRequest(
                **{_TOPIC_ARG: self._input_peer},
                offset_date=None,
                offset_id=0,
                offset_topic=offset_topic,
                limit=100,
            )))
            batch = list(result.topics or [])
            for topic in batch:
                topics.append({
                    'telegram_id': topic.id,
                    'title': topic.title,
                    'icon_emoji': getattr(topic, 'icon_emoji', None),
                    'is_closed': getattr(topic, 'closed', False),
                    'created_at': getattr(topic, 'date', None),
                })
            if len(batch) < 100:
                break
            offset_topic = batch[-1].id
        return topics

    async def get_messages(self, topic_id: Optional[int] = None, offset_id: int = 0,
                           limit: int = 100, reverse: bool = False) -> List[Message]:
        """Сообщения темы.

        ``reverse=False`` — от новых к старым (offset_id = верхняя граница),
        ``reverse=True``  — от старых к новым (offset_id = нижняя граница).
        """
        self._check_started()
        kwargs = dict(limit=limit, offset_id=offset_id, reverse=reverse, filter=None)
        if topic_id:
            messages = await self._call(lambda: self.client.get_messages(
                self._input_peer, reply_to=topic_id, **kwargs
            ))
        else:
            messages = await self._call(lambda: self.client.get_messages(self._input_peer, **kwargs))
        return list(messages or [])

    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        self._check_started()
        try:
            entity = await self._call(lambda: self.client.get_entity(user_id))
        except Exception as e:
            print(f"[!] Не удалось получить пользователя {user_id}: {e}")
            return {
                'telegram_id': user_id,
                'username': None,
                'first_name': 'Unknown',
                'last_name': '',
            }
        return self.user_to_dict(entity)

    @staticmethod
    def user_to_dict(entity) -> Dict[str, Any]:
        return {
            'telegram_id': entity.id,
            'username': getattr(entity, 'username', None),
            'first_name': getattr(entity, 'first_name', None),
            'last_name': getattr(entity, 'last_name', None),
        }

    def _check_started(self):
        if not self._started:
            raise RuntimeError("Клиент не запущен. Вызовите start() перед использованием.")
