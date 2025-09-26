import argparse
import yaml
from database import init_db
from telegram_client import TelegramArchiver
import asyncio

def load_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def init(config):
    db_path = config["storage"]["database"]
    print(f"[*] Инициализация БД: {db_path}")
    init_db(db_path)
    print("[+] База данных готова")

async def sync(config, verbose=False, topic_ids=None):
    print("[*] Синхронизация...")
    
    tg_config = config["telegram"]
    db_path = config["storage"]["database"]
    media_dir = config["storage"]["media_dir"]

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
    # TODO

def main():
    parser = argparse.ArgumentParser(description="Архиватор Telegram-групп")
    parser.add_argument("command", choices=["init", "sync", "generate"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--verbose", action="store_true", help="Включить подробный лог")
    parser.add_argument("--topics", nargs='+', type=int, help="ID тем для синхронизации (если не указаны — все)")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.command == "init":
        init(config)
    elif args.command == "sync":
        asyncio.run(sync(config, verbose=args.verbose, topic_ids=args.topics))
    elif args.command == "generate":
        generate(config)

if __name__ == "__main__":
    main()
