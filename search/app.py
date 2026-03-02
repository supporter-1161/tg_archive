# search/app.py
import os
import sys
import argparse
import requests
from flask import Flask, request, render_template

# -------------------------------------------------
# Аргументы командной строки
# -------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument(
    "--output-dir",
    default="output",
    help="Путь к output/ (для генерации ссылок)"
)
parser.add_argument(
    "--manticore-url",
    default="http://localhost:9308",
    help="URL Manticore HTTP API"
)
parser.add_argument(
    "--templates-dir",
    default="./templates",
    help="Путь к Jinja2 шаблонам"
)
parser.add_argument(
    "--port",
    type=int,
    default=5000,
    help="Порт Flask"
)

args = parser.parse_known_args()[0]

OUTPUT_DIR = os.path.abspath(args.output_dir)
#MANTICORE_URL = args.manticore_url.rstrip("/")
MANTICORE_URL = os.getenv("MANTICORE_URL", "http://manticore:9308").rstrip("/")
TEMPLATES_DIR = os.path.abspath(args.templates_dir)

# -------------------------------------------------
# Проверка шаблонов
# -------------------------------------------------
if not os.path.isdir(TEMPLATES_DIR):
    print(f"❌ Папка шаблонов не найдена: {TEMPLATES_DIR}", file=sys.stderr)
    sys.exit(1)

# -------------------------------------------------
# Flask app
# -------------------------------------------------
app = Flask(__name__, template_folder=TEMPLATES_DIR)

# -------------------------------------------------
# Поиск
# -------------------------------------------------
@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    if not query:
        return render_template(
            "results.html.j2",
            query="",
            results=[],
            total=0
        )

    # минимальное экранирование
    safe_query = query.replace("'", "\\'")

    sql = (
        "SELECT title, content, relative_url "
        "FROM html_index "
        f"WHERE MATCH('{safe_query}') "
        "LIMIT 50 "
        "OPTION ranker=proximity, max_matches=1000"
    )

    print("🔎 SQL:", sql)

    results = []
    total = 0

    try:
        r = requests.post(
            f"{MANTICORE_URL}/sql",
            data=sql,
            headers={"Content-Type": "text/plain"},
            timeout=10
        )

        if r.status_code != 200:
            print(
                f"❌ Manticore HTTP {r.status_code}: {r.text}",
                file=sys.stderr
            )
        else:
            data = r.json()

            # -----------------------------
            # ВАЖНО: Elastic-style ответ
            # -----------------------------
            hits_block = data.get("hits", {})
            hits = hits_block.get("hits", [])

            for hit in hits:
                src = hit.get("_source", {})
                src["_score"] = hit.get("_score")
                results.append(src)

            total = hits_block.get("total", 0)

    except Exception as e:
        print(f"❌ Ошибка поиска: {e}", file=sys.stderr)

    return render_template(
        "results.html.j2",
        query=query,
        results=results,
        total=total
    )

# -------------------------------------------------
# Entry point
# -------------------------------------------------
if __name__ == "__main__":
    app.run(
    host="0.0.0.0",
    port=args.port,
    debug=False,
    use_reloader=False
    )
