# tg-archive

Архив публичной Telegram-группы с форум-топиками: сообщения, медиа и пользователи
складываются в SQLite, затем публикуются как анонимный статический сайт с поиском.

Принцип сайта — **ноль JavaScript**. Навигация, пагинация и поиск работают на формах
и ссылках; тема оформления берётся из настроек системы через CSS. Это осознанно:
архив рассчитан на публикацию в вебе и в I2P, где меньше исполняемого кода — меньше
поверхности атаки и меньше утечек.

## Что умеет

* инкрементальная синхронизация: `forward` — только новое, `backward` — полный проход
  с заполнением дыр;
* топики форума, медиа (фото/видео/документы/аудио) с дедупликацией по `(id, access_hash)`,
  лимит размера файла;
* анонимный режим (никто из авторов не раскрывается), тёмная/светлая/системная тема;
* статический сайт: главная, страницы тем с пагинацией, отдельная страница на сообщение,
  превью изображений, альбомы по 2–10 фото в одной карточке;
* полнотекстовый поиск (Manticore) с морфологией, пагинацией и подсветкой — без JS;
* оформление настраивается: баннер в шапке, компоновка «текст слева / медиа справа»,
  заголовок блока ссылок.

## Оформление

```yaml
ui:
  theme: "auto"                 # dark | light | auto (системная тема)
  message_layout: "side"        # side = текст слева, медиа справа; stacked = под текстом
  useful_links_title: "Полезные ссылки"
  banner:
    path: "static/banner.jpg"   # скопируется в output как banner.jpg
    alt: "Баннер архива"
  media_max_width: 1000         # ширина превью; меньше — легче страницы
```

Баннер занимает всю ширину шапки и фиксированные 160px по высоте (90px на телефоне).
Каркас страниц: шапка и подвал закреплены, прокручивается только лента сообщений
(на странице темы пагинация тоже закреплена снизу). На узких экранах включается
обычная прокрутка страницы.

## Установка

```bash
python -m venv .venv            # или используйте ./bin/python из готового venv
./.venv/bin/pip install -r requirements.txt

cp config.example.yaml config.yaml
# впишите telegram.api_id, api_hash и group_id
```

`api_id`/`api_hash` берутся на https://my.telegram.org/apps. `group_id` — id форум-группы,
годится и `-1001234567890`, и «сырой» `-1234567890`.

## Работа

```bash
# 1. база и каталоги
./bin/python tg_archive.py init --config config.yaml

# 2. вход в Telegram (один раз, интерактивно: телефон, код, 2FA)
./bin/python tg_archive.py login --config config.yaml

# 3. синхронизация
./bin/python tg_archive.py sync --config config.yaml                 # новые сообщения
./bin/python tg_archive.py sync --config config.yaml --sync-direction backward  # вся история
./bin/python tg_archive.py sync --config config.yaml --topics 1143 --verbose    # одна тема

# 4. сайт
./bin/python tg_archive.py generate --config config.yaml

# 5. индекс поиска (Manticore должен быть запущен)
./bin/python tg_archive.py index --config config.yaml
```

Файлы больше `storage.max_media_size_mb` (по умолчанию 50 МБ) не скачиваются — сообщение
сохраняется с текстом, в лог пишется `[SKIP]`. Лимит можно переопределить на один запуск
(`--max-media-size-mb 0` — качать всё) или задать в конфиге, в том числе `0`.

## Docker

```bash
docker compose up -d manticore          # поисковый движок
docker compose run --rm tg_archive ./bin/python tg_archive.py sync --config config.yaml
docker compose run --rm tg_archive ./bin/python tg_archive.py generate --config config.yaml
docker compose run --rm tg_archive ./bin/python tg_archive.py index --config config.yaml
docker compose up -d search web         # gunicorn + nginx
```

Сайт слушает `127.0.0.1:8080`. Наружу его выставляйте через I2P-туннель или обратный
прокси с TLS; Manticore (9306/9308) специально привязан к localhost — у него нет
аутентификации.

## Безопасность

* текст сообщений экранируется до применения разметки; ссылки допускаются только
  `http/https/mailto` — stored XSS из сообщений закрыт;
* поиск ходит в Manticore через JSON API, SQL не склеивается;
* nginx: CSP `script-src 'none'`, `nosniff`, `no-referrer`, лимит запросов на `/search`,
  `access_log off` (IP посетителей не хранятся);
* Flask за gunicorn, non-root, read-only rootfs, `no-new-privileges`;
* `config.yaml`, `.session` и база в git не попадают.

## Тесты

```bash
./bin/python -m unittest discover -s tests -v
```

Покрыты: направления и пагинация синка, заполнение дыр, дубли, reply_to, служебные
сообщения, кеш пользователей, миграция схемы v1→v2, экранирование разметки.

## Схема БД

`sqlite3 tg_archive.db .schema`. Версия схемы — `PRAGMA user_version`; миграции
выполняются автоматически в `init_db` с бэкапом `*.pre-vN.bak`.

Таблицы: `topics`, `messages` (`reply_to_msg_id` — id сообщения, на которое ответ;
`topic_id` — id топика), `users`, `media_files`, `generation_stats`.

Подвал — одна строка: название, время генерации и число сообщений. Время выводится
в UTC и отключается через `ui.show_update_time`; слоган (`site.footer_text`)
показывается только если задан.
