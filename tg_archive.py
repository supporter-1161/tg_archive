from web_generator import generate_website
import argparse
import yaml
from database import init_db
from telegram_client import TelegramArchiver
import asyncio
import os 

def load_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def init(config):
    db_path = config["storage"]["database"]
    print(f"[*] Инициализация БД: {db_path}")
    init_db(db_path)
    print("[+] База данных готова")

    # --- Создание директорий ---
    storage_config = config["storage"]
    media_dir = storage_config["media_dir"]
    avatars_dir = storage_config.get("avatars_dir", "avatars") # <-- Допустим, avatars_dir может быть не указан, тогда по умолчанию "avatars"
    output_dir = storage_config.get("output_dir", "output")   # <-- Допустим, output_dir может быть не указан, тогда по умолчанию "output"

    directories_to_create = [media_dir, avatars_dir, output_dir]

    for dir_path in directories_to_create:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"[+] Создана директория: {dir_path}")
        else:
            print(f"[.] Директория уже существует: {dir_path}")
    # --- Конец создания директорий ---

    print("[+] Инициализация завершена")


async def sync(config, verbose=False, topic_ids=None, sync_direction='forward'): # <-- Добавлен sync_direction с значением по умолчанию
    print(f"[*] Синхронизация (направление: {sync_direction})...")
    tg_config = config["telegram"]
    db_path = config["storage"]["database"]
    media_dir = config["storage"]["media_dir"]
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"],
        sync_direction=sync_direction # <-- Передаём направление в TelegramArchiver
    )
    await archiver.start()
    await archiver.sync_topics_and_messages(db_path, media_dir, verbose=verbose, topic_ids=topic_ids, sync_direction=sync_direction) # <-- Передаём направление в sync_topics_and_messages
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
        # Передаём значение аргумента sync_direction в функцию sync
        asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics, sync_direction=args.sync_direction))
    elif args.command == "generate":
        generate(config)

if __name__ == "__main__":
    main()
