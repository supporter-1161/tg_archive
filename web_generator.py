# web_generator.py
import os
# shutil больше не нужен здесь, так как копирование вынесено в file_copier.py
from database import get_db_connection # <-- Возможно, больше не нужен, если HTMLGenerator сам подключается
import sqlite3 # <-- Возможно, больше не нужен, если HTMLGenerator сам подключается
from datetime import datetime # <-- Возможно, больше не нужен
import yaml # <-- Возможно, больше не нужен
import math  # <-- Возможно, больше не нужен

# --- ИМПОРТИРУЕМ НАШИ НОВЫЕ КЛАССЫ И ФУНКЦИИ ---
from web_gen.html_generator import HTMLGenerator # <-- Импортируем основной генератор HTML
from web_gen.file_copier import copy_static_resources, copy_media_files, copy_avatar_files # <-- Импортируем функции копирования
# --- КОНЕЦ ИМПОРТА ---

# --- Функции для работы с БД (удаляем, они теперь в db_queries.py) ---
# def get_db_stats(conn):
#     ...
# def get_topics(conn, ...):
#     ...
# ... и т.д.
# --- КОНЕЦ УДАЛЕННЫХ ФУНКЦИЙ ---

# --- Основной класс генератора (удаляем, он теперь в html_generator.py) ---
# class WebGenerator:
#     def __init__(self, ...):
#         ...
#     def generate(self):
#         ...
# --- КОНЕЦ УДАЛЁННОГО КЛАССА ---

# --- Основная функция generate_website ---
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
