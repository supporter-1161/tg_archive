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
from client.telegram_api_client import SessionNotAuthorized


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


async def sync(config, verbose=False, topic_ids=None, sync_direction='forward',
               max_media_size_mb=None):
    """Синхронизация. max_media_size_mb перекрывает значение из конфига."""
    print(f"[*] Синхронизация (направление: {sync_direction})...")
    tg_config = config["telegram"]
    db_path = config["storage"]["database"]
    media_dir = config["storage"]["media_dir"]
    if max_media_size_mb is None:
        max_media_size_mb = config["storage"].get("max_media_size_mb", 50)
    print(f"[*] Лимит медиа: {'без лимита' if not max_media_size_mb else f'{max_media_size_mb} МБ'}")
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"],
        sync_direction=sync_direction,
        max_media_size_mb=max_media_size_mb,
    )
    try:
        await archiver.start()
    except SessionNotAuthorized as e:
        print(f"[!] {e}")
        return 1
    try:
        await archiver.sync_topics_and_messages(db_path, media_dir, verbose=verbose, topic_ids=topic_ids, sync_direction=sync_direction)
    finally:
        await archiver.close()
    return 0


async def login(config):
    """Интерактивный вход в Telegram (один раз, потом сессия переиспользуется)."""
    tg_config = config["telegram"]
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"],
    )
    await archiver.api_client.login()
    await archiver.close()


def generate(config):
    print("[*] Генерация сайта...")
    generate_website(config)


def index(config, config_path=None, manticore_url=None, index_name=None):
    search_config = config.get("search", {}) or {}
    manticore_url = manticore_url or search_config.get("manticore_url")
    index_name = index_name or search_config.get("index_name")

    cmd = [sys.executable, "-m", "search.create_index"]
    if config_path:
        cmd += ["--config", config_path]
    else:
        cmd += ["--db", config["storage"]["database"]]
    if manticore_url:
        cmd += ["--manticore-url", manticore_url]
    if index_name:
        cmd += ["--index-name", index_name]

    print(f"[*] Запуск: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True)
        if result.returncode == 0:
            print("[+] Индексация завершена успешно")
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"⚠ Индексация завершилась с ошибкой: {e}")
        return 1
    except FileNotFoundError:
        print("❌ Ошибка: модуль search.create_index не найден")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Архиватор Telegram-групп")
    parser.add_argument("command", choices=["init", "login", "sync", "generate", "index"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true", help="Включить подробный лог")
    parser.add_argument("--topics", nargs='+', type=int, help="ID тем для синхронизации")
    parser.add_argument("--sync-direction", choices=["forward", "backward"], default="forward", help="Направление синхронизации")
    parser.add_argument("--max-media-size-mb", type=int, default=None,
                        help="Лимит размера файла в МБ для этого запуска (0 = без лимита)")
    # === НОВОЕ: опции для индексации ===
    parser.add_argument("--manticore-url", default=None, help="URL Manticore HTTP API (для команды index)")
    parser.add_argument("--index-name", default=None, help="Имя индекса в Manticore (для команды index)")
    # ===================================

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "init":
        init(config)
    elif args.command == "login":
        asyncio.run(login(config))
    elif args.command == "sync":
        sys.exit(asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics,
                                  sync_direction=args.sync_direction,
                                  max_media_size_mb=args.max_media_size_mb)))
    elif args.command == "generate":
        generate(config)
    elif args.command == "index":
        sys.exit(index(config, config_path=args.config,
                       manticore_url=args.manticore_url, index_name=args.index_name))


if __name__ == "__main__":
    main()
