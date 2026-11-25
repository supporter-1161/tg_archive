# web_generator.py
"""Генерация статического сайта: HTML + статика + медиа."""
from database import init_db
from web_gen.html_generator import HTMLGenerator
from web_gen.file_copier import copy_static_resources, copy_media_files, copy_avatar_files


def generate_website(config):
    db_path = config["storage"]["database"]
    output_dir = config["storage"].get("output_dir", "output")

    # Генерация читает схему напрямую: если база старой версии, приводим её
    # к актуальной здесь, а не падаем на отсутствующей колонке.
    init_db(db_path)

    html_gen = HTMLGenerator(config, db_path, output_dir)
    html_gen.generate()

    copy_static_resources('static', output_dir)
    copy_media_files(config, output_dir)
    copy_avatar_files(config, output_dir)

    print("[+] Генерация веб-сайта завершена (HTML и файлы).")
