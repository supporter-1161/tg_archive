# web_generator.py
from datetime import datetime # <-- Возможно, больше не нужен
from web_gen.html_generator import HTMLGenerator # <-- Импортируем основной генератор HTML
from web_gen.file_copier import copy_static_resources, copy_media_files, copy_avatar_files # <-- Импортируем функции копирования

def generate_website(config):
    db_path = config["storage"]["database"]
    output_dir = config["storage"].get("output_dir", "output")

    # Создаём HTMLGenerator и вызываем его метод generate
    html_gen = HTMLGenerator(config, db_path, output_dir)
    html_gen.generate()

    # После генерации HTML, копируем ресурсы
    copy_static_resources('static', output_dir)
    copy_media_files(config, output_dir)
    copy_avatar_files(config, output_dir)

    print(f"[+] Генерация веб-сайта завершена (HTML и файлы).")
