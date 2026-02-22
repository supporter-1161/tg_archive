# search/create_index.py
import os
import sys
import json
import argparse
import requests
from bs4 import BeautifulSoup


# -------------------------------------------------
# Управление таблицей
# -------------------------------------------------
def drop_table_if_exists(manticore_url: str, index_name: str):
    sql = f"DROP TABLE IF EXISTS {index_name}"

    r = requests.post(
        f"{manticore_url}/cli",
        data=sql,
        headers={"Content-Type": "text/plain"},
        timeout=10
    )

    if r.status_code != 200:
        raise Exception(f"Ошибка DROP TABLE: {r.status_code} {r.text}")

    print(f"🧨 Таблица `{index_name}` удалена (если существовала)")


def create_table_with_morphology(manticore_url: str, index_name: str):
    sql = (
        f"CREATE TABLE {index_name} ("
        "title text, "
        "content text, "
        "relative_url string"
        ") WITH ("
        "morphology = 'stem_ru'"
        ")"
    )

    r = requests.post(
        f"{manticore_url}/cli",
        data=sql,
        headers={"Content-Type": "text/plain"},
        timeout=10
    )

    if r.status_code != 200:
        raise Exception(f"Ошибка CREATE TABLE: {r.status_code} {r.text}")

    print(f"🌿 Таблица `{index_name}` создана с morphology=stem_ru")


# -------------------------------------------------
# Парсинг HTML
# -------------------------------------------------
def parse_message_html_file(path: str, base_output_dir: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    basename = os.path.basename(path)
    if basename.startswith("message_") and basename.endswith(".html"):
        msg_id = basename[len("message_"):-len(".html")]
        title = f"Сообщение #{msg_id}"
    else:
        title = basename

    content_parts = []
    for elem in soup.select(".message-text"):
        text = elem.get_text(separator=" ", strip=True)
        if text:
            content_parts.append(text)

    content = " ".join(content_parts)

    relative_url = os.path.relpath(path, base_output_dir).replace(os.sep, "/")

    return {
        "title": title,
        "content": content,
        "relative_url": relative_url
    }


def list_message_files(output_dir: str) -> list:
    messages_dir = os.path.join(output_dir, "messages")
    if not os.path.isdir(messages_dir):
        print(f"⚠ Каталог {messages_dir} не найден")
        return []

    files = []
    for name in os.listdir(messages_dir):
        if name.startswith("message_") and name.endswith(".html"):
            files.append(os.path.join(messages_dir, name))

    return sorted(files)


# -------------------------------------------------
# Bulk insert
# -------------------------------------------------
def bulk_insert_to_manticore(docs: list, manticore_url: str, index_name: str):
    lines = []

    for doc in docs:
        lines.append(json.dumps({
            "insert": {
                "table": index_name,
                "doc": doc
            }
        }))

    body = "\n".join(lines) + "\n"

    r = requests.post(
        f"{manticore_url}/bulk",
        data=body,
        headers={"Content-Type": "application/x-ndjson"},
        timeout=30
    )

    if r.status_code != 200:
        print(f"❌ Bulk insert failed: {r.text}")
        return False

    print("✅ Документы успешно загружены в Manticore")
    return True


# -------------------------------------------------
# Main
# -------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Индексация HTML-сообщений в Manticore Search с морфологией"
    )
    parser.add_argument(
        "--html-dir",
        required=True,
        help="Путь к output/ директории (например, ./output)"
    )
    parser.add_argument(
        "--manticore-url",
        default="http://localhost:9308",
        help="URL Manticore HTTP API"
    )
    parser.add_argument(
        "--index-name",
        default="html_index",
        help="Имя таблицы в Manticore"
    )

    args = parser.parse_args()

    output_dir = os.path.abspath(args.html_dir)
    manticore_url = args.manticore_url.rstrip("/")
    index_name = args.index_name

    print("📦 Запуск индексации сообщений")
    print("=" * 50)
    print(f"📂 Директория: {output_dir}")
    print(f"🔍 Источник: {output_dir}/messages/")
    print(f"🔗 Manticore: {manticore_url}")
    print(f"🗃️  Таблица: {index_name}")
    print("=" * 50)

    files = list_message_files(output_dir)
    print(f"📁 Найдено HTML-файлов: {len(files)}")

    if not files:
        print("⚠ Нет файлов для индексации")
        return 1

    docs = []
    total = len(files)

    for i, path in enumerate(files, 1):
        print(f"[{i}/{total}] {os.path.basename(path)}")
        try:
            doc = parse_message_html_file(path, output_dir)
            if doc["content"].strip():
                docs.append(doc)
        except Exception as e:
            print(f"⚠ Ошибка парсинга {path}: {e}")

    print(f"📤 Подготовлено документов: {len(docs)}")

    if not docs:
        print("⚠ Нет документов с текстом для индексации")
        return 1

    # --- управление таблицей ---
    drop_table_if_exists(manticore_url, index_name)
    create_table_with_morphology(manticore_url, index_name)

    print("📤 Отправка документов в Manticore...")
    ok = bulk_insert_to_manticore(docs, manticore_url, index_name)

    if ok:
        print("🎉 Индексация завершена успешно")
        return 0
    else:
        print("❌ Ошибка индексации")
        return 1


if __name__ == "__main__":
    sys.exit(main())
