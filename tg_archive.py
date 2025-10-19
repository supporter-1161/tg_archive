# tg_archive.py
from config import load_config
from web_generator import generate_website
import argparse
import asyncio
import os
from database import init_db
# --- ИМПОРТ ИЗМЕНЁН ---
from telegram_client import TelegramArchiver # <-- Теперь импортируем из корня
# --- КОНЕЦ ИМПОРТА ---
import yaml # <-- Добавим yaml сюда, если он понадобится, но load_config уже в config.py

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
    # --- ИЗМЕНЕНИЕ СОЗДАНИЯ TelegramArchiver ---
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"],
        sync_direction=sync_direction
    )
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---
    await archiver.start()
    await archiver.sync_topics_and_messages(db_path, media_dir, verbose=verbose, topic_ids=topic_ids, sync_direction=sync_direction)
    await archiver.close()

def generate(config):
    print("[*] Генерация сайта...")
    generate_website(config)
    pass

def main():
    parser = argparse.ArgumentParser(description="Архиватор Telegram-групп")
    parser.add_argument("command", choices=["init", "sync", "generate"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true", help="Включить подробный лог")
    parser.add_argument("--topics", nargs='+', type=int, help="ID тем для синхронизации (если не указаны — все)")
    parser.add_argument("--sync-direction", choices=["forward", "backward"], default="forward", help="Направление синхронизации: 'forward' (новые сообщения) или 'backward' (старые сообщения).")
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "init":
        init(config)
    elif args.command == "sync":
        asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics, sync_direction=args.sync_direction))
    elif args.command == "generate":
        generate(config)

if __name__ == "__main__":
    main()
