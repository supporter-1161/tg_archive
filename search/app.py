"""Flask-поиск по архиву.

Работает только за nginx (наружу не публикуется) и общается с Manticore
через JSON /search — SQL-строки не собираются, инъекции неоткуда взяться.
Вся пользовательская выдача экранируется, разметка — только наша (autoescape).
"""
import html
import math
import os
import re
from typing import Dict, List, Tuple

import requests
import yaml
from flask import Flask, jsonify, render_template, request

MAX_QUERY_LEN = 120
MAX_PAGE = 50
CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')
# Символы, которые Manticore трактует как операторы запроса.
QUERY_OPERATORS = re.compile(r'[@()|!~\\"`$\-/]')
# Разметка Telegram, которую не стоит показывать в сниппете выдачи.
MARKUP = re.compile(r'\*\*|__|~~|```|`|\[([^\]]+)\]\([^)]+\)')


def strip_markup(text: str) -> str:
    """Убирает markdown-маркеры из текста сообщения (для сниппета)."""
    return MARKUP.sub(lambda m: m.group(1) or '', text or '')


def load_config(path: str) -> Dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[!] Не удалось прочитать {path}: {e}")
        return {}


def clean_query(raw: str) -> str:
    q = CONTROL_CHARS.sub(' ', raw or '')
    q = QUERY_OPERATORS.sub(' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q[:MAX_QUERY_LEN]


def make_snippet(content: str, terms: List[str], width: int = 280) -> str:
    """Безопасный сниппет: экранируем, потом подсвечиваем <mark>."""
    text = strip_markup(content)
    lower = text.lower()
    positions = [lower.find(t) for t in terms if t and lower.find(t) >= 0]
    pos = min(positions) if positions else 0
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    fragment = text[start:end]

    escaped = html.escape(fragment)
    for term in sorted({t for t in terms if len(t) >= 2}, key=len, reverse=True):
        escaped_term = html.escape(term)
        if not escaped_term:
            continue
        escaped = re.sub(re.escape(escaped_term),
                         lambda m: f'<mark>{m.group(0)}</mark>',
                         escaped, flags=re.IGNORECASE)
    prefix = '… ' if start > 0 else ''
    suffix = ' …' if end < len(text) else ''
    return prefix + escaped + suffix


def create_app() -> Flask:
    config_path = os.getenv('TG_ARCHIVE_CONFIG', 'config.yaml')
    config = load_config(config_path)
    search_cfg = config.get('search', {}) or {}

    manticore_url = (os.getenv('MANTICORE_URL')
                     or search_cfg.get('manticore_url')
                     or 'http://manticore:9308').rstrip('/')
    index_name = os.getenv('MANTICORE_INDEX') or search_cfg.get('index_name') or 'html_index'
    per_page = int(os.getenv('SEARCH_PER_PAGE') or search_cfg.get('per_page') or 20)
    templates_dir = os.getenv(
        'TEMPLATES_DIR',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates'),
    )

    app = Flask(__name__, template_folder=templates_dir)
    # Шаблоны называются *.html.j2, а Flask по умолчанию включает autoescape
    # только для *.html/*.xml — без этого пользовательский запрос попадал в
    # страницу как HTML (XSS через ?q=<script>).
    app.jinja_env.autoescape = True
    app.jinja_env.cache = None
    site = config.get('site', {}) or {}

    def render_results(query: str, page: int, results: List[Dict], total: int,
                       error: str = ''):
        total_pages = min(MAX_PAGE, math.ceil(total / per_page)) if total else 0
        return render_template(
            'results.html.j2',
            query=query,
            results=results,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            error=error,
            site_title=site.get('title', 'Архив Telegram'),
            site_description=site.get('description', ''),
            footer_text=site.get('footer_text', ''),
            default_theme=config.get('ui', {}).get('theme', 'light'),
        )

    @app.get('/search')
    def search():
        original = request.args.get('q', '')
        query = clean_query(original)
        try:
            page = max(1, min(MAX_PAGE, int(request.args.get('page', 1))))
        except ValueError:
            page = 1

        if not query:
            return render_results(query='', page=1, results=[], total=0)

        terms = [t for t in query.split() if len(t) >= 2]
        payload = {
            'index': index_name,
            'query': {'match': {'content': {'query': query, 'operator': 'and'}}},
            'limit': per_page,
            'offset': (page - 1) * per_page,
            'options': {'max_matches': 1000, 'ranker': 'proximity_bm25'},
        }

        try:
            r = requests.post(f'{manticore_url}/search', json=payload, timeout=8)
        except requests.RequestException as e:
            print(f"[!] Manticore недоступен: {e}")
            return render_results(query=query, page=page, results=[], total=0,
                                  error='Поиск временно недоступен.')

        if r.status_code != 200:
            print(f"[!] Manticore HTTP {r.status_code}: {r.text[:300]}")
            return render_results(query=query, page=page, results=[], total=0,
                                  error='Поиск временно недоступен.')

        data = r.json()
        hits_block = data.get('hits', {}) or {}
        total = int(hits_block.get('total', 0) or 0)

        results = []
        for hit in hits_block.get('hits', []) or []:
            source = hit.get('_source', {}) or {}
            content = source.get('content', '') or ''
            results.append({
                'title': source.get('title', ''),
                'relative_url': source.get('relative_url', ''),
                'snippet': make_snippet(content, terms),
            })

        return render_results(query=query, page=page, results=results, total=total)

    @app.get('/healthz')
    def healthz():
        try:
            r = requests.post(f'{manticore_url}/cli',
                              data=f"SHOW TABLES LIKE '{index_name}'",
                              headers={'Content-Type': 'text/plain'}, timeout=3)
            ok = r.status_code == 200 and index_name in r.text
        except requests.RequestException:
            ok = False
        return jsonify({'status': 'ok' if ok else 'degraded',
                        'index': index_name, 'manticore': manticore_url}), (200 if ok else 503)

    return app


app = create_app()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Поиск по архиву (dev-сервер)")
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', default='127.0.0.1')
    args, _ = parser.parse_known_args()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
