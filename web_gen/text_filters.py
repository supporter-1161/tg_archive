"""Вырезание мусорных строк (реклама, призывы подписаться, разделители).

Фильтр работает на этапе генерации: в базе текст остаётся как есть, поэтому
словарь можно править и перегенерировать статику без повторного синка.

Формат словаря (``filters.txt``): по одному правилу на строку, ``#`` — комментарий.
Если правило встречается внутри строки сообщения, вся строка выбрасывается.
Строки из одних символов-разделителей (``---``, ``===``, ``___``) выбрасываются
отдельным встроенным правилом.

Сравнение идёт по «очищенной» строке, чтобы эмодзи и разметка не мешали:

* markdown-ссылка ``[текст](url)`` сравнивается и по ``текст``, и по адресу:
  правило ``🕹КиберТопор — Подписаться`` совпадает со строкой
  ``🕹[КиберТопор — Подписаться](https://t.me/...)``, а ``t.me/it_mega_g`` —
  со строкой ``[IT MEGA](https://t.me/it_mega_g)``;
* убираются ``*``, ``_``, обратные кавычки и вариационные селекторы
  (U+FE0E/U+FE0F), поэтому ``🕹️`` в словаре и ``🕹`` в сообщении равны;
* всё приводится к NFKC и нижнему регистру.
"""

import os
import re
import unicodedata

# Строка целиком состоит из символов-разделителей: ----, =====, ***, ___ ...
SEPARATOR_RE = re.compile(r'^[\s\-=_*~—–.·•#]{3,}$')

# [текст](url) -> текст ; [текст] -> текст
MD_LINK_RE = re.compile(r'\[([^\]]*)\](?:\([^)]*\))?')

# Символы разметки, которые не должны влиять на совпадение.
MARKUP_CHARS = '*_`'

_cache = {'path': None, 'mtime': None, 'rules': ()}


def normalize(text, keep_links=False):
    """Приводит строку к виду, по которому сравниваем правила.

    keep_links=True оставляет адреса ссылок: тогда правило вида
    ``t.me/it_mega_g`` ловит строку ``[IT MEGA](https://t.me/it_mega_g)``.
    """
    if not keep_links:
        text = MD_LINK_RE.sub(r'\1', text)
    for ch in MARKUP_CHARS:
        text = text.replace(ch, '')
    # Вариационные селекторы: 🕹️ (U+1F579 U+FE0F) и 🕹 (U+1F579) — один эмодзи.
    text = text.replace('\ufe0e', '').replace('\ufe0f', '')
    text = unicodedata.normalize('NFKC', text)
    return text.casefold()


def load_rules(path):
    """Читает словарь и возвращает кортеж нормализованных правил (кэш по mtime)."""
    if not path:
        return ()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ()

    if _cache['path'] == path and _cache['mtime'] == mtime:
        return _cache['rules']

    rules = []
    try:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                rule = normalize(line)
                if rule:
                    rules.append(rule)
    except OSError as e:
        print(f"[!] Словарь фильтров {path}: {e}")

    _cache.update(path=path, mtime=mtime, rules=tuple(rules))
    return _cache['rules']


def clean_text(text, rules=(), remove_separators=True):
    """Убирает из текста строки, совпавшие со словарём, и разделители."""
    if not text:
        return text
    if not rules and not remove_separators:
        return text

    kept = []
    removed = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            kept.append('')
            continue
        if remove_separators and SEPARATOR_RE.match(stripped):
            removed += 1
            continue
        if rules:
            plain = normalize(stripped)
            with_links = normalize(stripped, keep_links=True)
            if any(rule in plain or rule in with_links for rule in rules):
                removed += 1
                continue
        kept.append(line)

    if not removed:
        return text

    # Схлопываем пустые строки, оставшиеся от вырезанных абзацев.
    out = re.sub(r'\n{3,}', '\n\n', '\n'.join(kept))
    return out.strip('\n')
