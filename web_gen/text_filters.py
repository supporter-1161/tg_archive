"""Вырезание мусорных строк (реклама, призывы подписаться, разделители).

Фильтр работает на этапе генерации: в базе текст остаётся как есть, поэтому
словарь можно править и перегенерировать статику без повторного синка.

Формат словаря (``filters.txt``): по одному правилу на строку, ``#`` — комментарий.
Если правило встречается внутри строки сообщения (без учёта регистра), вся строка
выбрасывается. Строки из одних символов-разделителей (``---``, ``===``, ``___``)
выбрасываются отдельным встроенным правилом.
"""

import os
import re

# Строка целиком состоит из символов-разделителей: ----, =====, ***, ___ ...
SEPARATOR_RE = re.compile(r'^[\s\-=_*~—–.·•#]{3,}$')

_cache = {'path': None, 'mtime': None, 'rules': ()}


def load_rules(path):
    """Читает словарь и возвращает кортеж правил в нижнем регистре (кэш по mtime)."""
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
                rules.append(line.casefold())
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
        folded = stripped.casefold()
        if any(rule in folded for rule in rules):
            removed += 1
            continue
        kept.append(line)

    if not removed:
        return text

    # Схлопываем пустые строки, оставшиеся от вырезанных абзацев.
    out = re.sub(r'\n{3,}', '\n\n', '\n'.join(kept))
    return out.strip('\n')
