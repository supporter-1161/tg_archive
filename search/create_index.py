"""Индексация архива в Manticore.

Документы берутся напрямую из SQLite, а не парсингом сгенерированных HTML:
это быстрее, не зависит от вёрстки и не требует BeautifulSoup.

Индекс собирается в таблицу ``<index>_new`` и подменяет рабочую одной
атомарной командой RENAME — поиск не лежит во время переиндексации.
"""
import argparse
import json
import os
import sqlite3
import sys
from typing import Dict, List

import requests

BATCH_SIZE = 500


class ManticoreError(RuntimeError):
    pass


def manticore_sql(url: str, statement: str):
    """Выполняет SQL через HTTP /cli. Используется только для DDL.

    Manticore умеет отвечать HTTP 200 и «Query OK» на синтаксически неверный
    DDL (например, старый вариант `CREATE TABLE ... WITH (...)` в 14.x просто
    ничего не создаёт), поэтому проверяем и тело ответа.
    """
    r = requests.post(f"{url}/cli", data=statement,
                      headers={"Content-Type": "text/plain"}, timeout=30)
    if r.status_code != 200:
        raise ManticoreError(f"{statement.split()[0]}: HTTP {r.status_code} {r.text[:300]}")
    body = (r.text or '').strip()
    if body.startswith('{') and '"error"' in body:
        raise ManticoreError(f"{statement.split()[0]}: {body[:300]}")
    if body.upper().startswith('ERROR'):
        raise ManticoreError(f"{statement.split()[0]}: {body[:300]}")
    return r


def bulk_insert(url: str, index_name: str, docs: List[Dict]) -> None:
    """Вставка через /bulk NDJSON — без склейки SQL-строк."""
    lines = [
        json.dumps({"insert": {"index": index_name, "doc": doc}}, ensure_ascii=False)
        for doc in docs
    ]
    body = ("\n".join(lines) + "\n").encode("utf-8")
    r = requests.post(f"{url}/bulk", data=body,
                      headers={"Content-Type": "application/x-ndjson"}, timeout=120)
    if r.status_code != 200:
        raise ManticoreError(f"bulk: HTTP {r.status_code} {r.text[:300]}")
    payload = r.json()
    if payload.get("errors"):
        raise ManticoreError(f"bulk errors: {json.dumps(payload)[:500]}")


def table_exists(url: str, index_name: str) -> bool:
    try:
        r = requests.post(f"{url}/cli", data=f"SHOW TABLES LIKE '{index_name}'",
                          headers={"Content-Type": "text/plain"}, timeout=10)
        return r.status_code == 200 and index_name in r.text
    except requests.RequestException:
        return False


def create_table(url: str, index_name: str) -> None:
    # Синтаксис именно `morphology='stem_ru'`: вариант `WITH (morphology=...)`
    # в Manticore 14 отвечает «Query OK», но таблицу не создаёт.
    manticore_sql(url, (
        f"CREATE TABLE {index_name} ("
        "title text, "
        "content text, "
        "relative_url string, "
        "topic_id bigint, "
        "msg_id bigint"
        ") morphology='stem_ru'"
    ))
    if not table_exists(url, index_name):
        raise ManticoreError(f"таблица {index_name} не создалась")


def collect_docs(db_path: str) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT m.telegram_id, m.topic_id, m.text, t.title AS topic_title
            FROM messages m
            LEFT JOIN topics t ON t.telegram_id = m.topic_id
            WHERE m.text IS NOT NULL AND TRIM(m.text) <> ''
        """).fetchall()
    finally:
        conn.close()

    docs = []
    for row in rows:
        topic_title = row['topic_title'] or 'Без темы'
        docs.append({
            'msg_id': row['telegram_id'],
            'topic_id': row['topic_id'] or 0,
            'title': f"#{row['telegram_id']} · {topic_title}",
            'content': row['text'],
            'relative_url': f"messages/message_{row['telegram_id']}.html",
        })
    return docs


def reindex(db_path: str, manticore_url: str, index_name: str) -> int:
    manticore_url = manticore_url.rstrip('/')
    docs = collect_docs(db_path)
    print(f"📦 Документов к индексации: {len(docs)}")
    if not docs:
        print("⚠ Нечего индексировать")
        return 0

    staging = f"{index_name}_new"
    manticore_sql(manticore_url, f"DROP TABLE IF EXISTS {staging}")
    create_table(manticore_url, staging)

    for start in range(0, len(docs), BATCH_SIZE):
        bulk_insert(manticore_url, staging, docs[start:start + BATCH_SIZE])
        print(f"  вставлено {min(start + BATCH_SIZE, len(docs))}/{len(docs)}")

    if table_exists(manticore_url, index_name):
        old = f"{index_name}_old"
        manticore_sql(manticore_url, f"DROP TABLE IF EXISTS {old}")
        # RENAME TABLE ... TO ... (две пары в одном запросе) через /cli молча
        # не срабатывает, поэтому два ALTER: окно, когда индекса нет, — доли
        # секунды, и приложение на это время отдаёт «поиск недоступен».
        manticore_sql(manticore_url, f"ALTER TABLE {index_name} RENAME TO {old}")
        manticore_sql(manticore_url, f"ALTER TABLE {staging} RENAME TO {index_name}")
        manticore_sql(manticore_url, f"DROP TABLE IF EXISTS {old}")
    else:
        manticore_sql(manticore_url, f"ALTER TABLE {staging} RENAME TO {index_name}")

    if not table_exists(manticore_url, index_name):
        raise ManticoreError(f"индекс {index_name} не появился после замены")
    print(f"✅ Индекс {index_name} обновлён")
    return len(docs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Индексация архива в Manticore")
    parser.add_argument("--db", default=None, help="Путь к tg_archive.db")
    parser.add_argument("--config", default="config.yaml", help="config.yaml")
    parser.add_argument("--manticore-url", default=None)
    parser.add_argument("--index-name", default=None)
    args = parser.parse_args()

    config = {}
    if os.path.exists(args.config):
        import yaml
        with open(args.config, encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

    search_cfg = config.get('search', {}) or {}
    db_path = args.db or (config.get('storage', {}) or {}).get('database', 'tg_archive.db')
    url = args.manticore_url or search_cfg.get('manticore_url') or 'http://localhost:9308'
    index_name = args.index_name or search_cfg.get('index_name') or 'html_index'

    print(f"🗃️  БД: {db_path}")
    print(f"🔗 Manticore: {url}")
    print(f"📑 Индекс: {index_name}")
    try:
        reindex(db_path, url, index_name)
    except ManticoreError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
