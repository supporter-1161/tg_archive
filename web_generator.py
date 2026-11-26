# web_generator.py
"""Генерация статического сайта: HTML + статика + медиа."""
import os
import shutil

from database import init_db
from web_gen.html_generator import HTMLGenerator
from web_gen.file_copier import copy_static_resources, copy_media_files, copy_avatar_files


def copy_banner(config, output_dir):
    """Кладёт баннер из конфига в корень output под предсказуемым именем."""
    banner_cfg = (config.get('ui') or {}).get('banner') or {}
    path = banner_cfg.get('path')
    if not path or not os.path.exists(path):
        return
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    dst = os.path.join(output_dir, f"banner{ext}")
    if not os.path.exists(dst) or os.path.getmtime(path) > os.path.getmtime(dst):
        shutil.copy2(path, dst)
        print(f"[+] Баннер скопирован: {dst}")


def generate_website(config):
    db_path = config["storage"]["database"]
    output_dir = config["storage"].get("output_dir", "output")

    # Генерация читает схему напрямую: если база старой версии, приводим её
    # к актуальной здесь, а не падаем на отсутствующей колонке.
    init_db(db_path)

    # Медиа и превью копируются ДО рендера: размер превью нужен в HTML.
    copy_media_files(config, output_dir)

    html_gen = HTMLGenerator(config, db_path, output_dir)
    html_gen.generate()

    copy_static_resources('static', output_dir)
    copy_banner(config, output_dir)
    copy_avatar_files(config, output_dir)

    print("[+] Генерация веб-сайта завершена (HTML и файлы).")
