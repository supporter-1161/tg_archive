# tg_archive.py
import subprocess
import os
import sys
import argparse
import asyncio
from config import load_config
from web_generator import generate_website
from database import init_db
from telegram_client import TelegramArchiver


def init(config):
    db_path = config["storage"]["database"]
    print(f"[*] Инициализация БД: {db_path}")
    init_db(db_path)
    print("[+] База данных готова")

    # --- Создание директорий ---
    storage_config = config["storage"]
    media_dir = storage_config["media_dir"]
    avatars_dir = storage_config.get("avatars_dir", "avatars")
    output_dir = storage_config.get("output_dir", "output")
    directories_to_create = [media_dir, avatars_dir, output_dir]
    for dir_path in directories_to_create:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"[+] Создана директория: {dir_path}")
        else:
            print(f"[.] Директория уже существует: {dir_path}")
    # --- Конец создания директорий ---
    print("[+] Инициализация завершена")


async def sync(config, verbose=False, topic_ids=None, sync_direction='forward'):
    print(f"[*] Синхронизация (направление: {sync_direction})...")
    tg_config = config["telegram"]
    db_path = config["storage"]["database"]
    media_dir = config["storage"]["media_dir"]
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"],
        sync_direction=sync_direction
    )
    await archiver.start()
    await archiver.sync_topics_and_messages(db_path, media_dir, verbose=verbose, topic_ids=topic_ids, sync_direction=sync_direction)
    await archiver.close()


def generate(config):
    print("[*] Генерация сайта...")
    generate_website(config)


def index(config, manticore_url=None, index_name=None):
    output_dir = config["storage"].get("output_dir", "output")

    cmd = [
        sys.executable,  # текущий интерпретатор (например, /venv/bin/python)
        "-m", "search.create_index",
        "--html-dir", output_dir
    ]
    if manticore_url:
        cmd += ["--manticore-url", manticore_url]
    if index_name:
        cmd += ["--index-name", index_name]

    print(f"[*] Запуск: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True)
        print("[+] Индексация завершена успешно")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"⚠ Индексация завершилась с ошибкой: {e}")
        return 1
    except FileNotFoundError:
        print("❌ Ошибка: файл search/create_index.py не найден")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Архиватор Telegram-групп")
    parser.add_argument("command", choices=["init", "sync", "generate", "index"])  # ← добавили "index"
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true", help="Включить подробный лог")
    parser.add_argument("--topics", nargs='+', type=int, help="ID тем для синхронизации")
    parser.add_argument("--sync-direction", choices=["forward", "backward"], default="forward", help="Направление синхронизации")
    # === НОВОЕ: опции для индексации ===
    parser.add_argument("--manticore-url", default="http://localhost:9308", help="URL Manticore HTTP API (для команды index)")
    parser.add_argument("--index-name", default="html_index", help="Имя индекса в Manticore (для команды index)")
    # ===================================

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "init":
        init(config)
    elif args.command == "sync":
        asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics, sync_direction=args.sync_direction))
    elif args.command == "generate":
        generate(config)
    elif args.command == "index":
        index(config, manticore_url=args.manticore_url, index_name=args.index_name)


if __name__ == "__main__":
    main()
