import argparse
import yaml
from database import init_db
from telegram_client import TelegramArchiver
import asyncio
import os # <-- Добавим импорт os

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

async def sync(config, verbose=False, topic_ids=None):
    print("[*] Синхронизация...")
    tg_config = config["telegram"]
    db_path = config["storage"]["database"]
    media_dir = config["storage"]["media_dir"] # <-- Убедимся, что media_dir указан в config.yaml
    archiver = TelegramArchiver(
        api_id=tg_config["api_id"],
        api_hash=tg_config["api_hash"],
        session_name=tg_config["session_name"],
        group_id=tg_config["group_id"]
    )
    await archiver.start()
    await archiver.sync_topics_and_messages(db_path, media_dir, verbose=verbose, topic_ids=topic_ids)
    await archiver.close()

def generate(config):
    print("[*] Генерация сайта...")
    # TODO: Проверить и создать output_dir и avatars_dir, если нужно, или доверить это генератору
    # storage_config = config["storage"]
    # output_dir = storage_config.get("output_dir", "output")
    # avatars_dir = storage_config.get("avatars_dir", "avatars")
    # os.makedirs(output_dir, exist_ok=True)
    # os.makedirs(avatars_dir, exist_ok=True)
    pass # <-- Пока заглушка

def main():
    parser = argparse.ArgumentParser(description="Архиватор Telegram-групп")
    parser.add_argument("command", choices=["init", "sync", "generate"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true", help="Включить подробный лог")
    parser.add_argument("--topics", nargs='+', type=int, help="ID тем для синхронизации (если не указаны — все)")
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "init":
        init(config) # <-- Теперь init создаст и директории
    elif args.command == "sync":
        asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics))
    elif args.command == "generate":
        generate(config)

if __name__ == "__main__":
    main()
