# web_gen/file_copier.py
import shutil
import os
from pathlib import Path
from typing import Dict, Any
from .image_resizer import resize_image_if_needed

def copy_static_resources(static_src: str, output_dir: str):
    static_dst = os.path.join(output_dir, 'static')
    if os.path.exists(static_src):
        if os.path.exists(static_dst):
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)
        print(f"[+] Скопированы статические ресурсы из '{static_src}' в '{static_dst}'")
    else:
        print(f"[!] Исходная директория статики не найдена: {static_src}")

def copy_media_files(config: Dict[str, Any], output_dir: str):
    media_src = config.get('storage', {}).get('media_dir', 'media')
    media_original_dst = os.path.join(output_dir, 'media', 'original')
    media_thumbs_dst = os.path.join(output_dir, 'media', 'thumbs')

    if not os.path.exists(media_src):
        print(f"[!] Исходная директория медиа не найдена: {media_src}")
        return

    # --- Копируем оригиналы ---
    if os.path.exists(media_original_dst):
        shutil.rmtree(media_original_dst)
    shutil.copytree(media_src, media_original_dst)
    print(f"[+] Оригиналы скопированы в: {media_original_dst}")

    # --- Генерируем миниатюры ---
    max_width = config.get('ui', {}).get('media_max_width', None)
    if max_width is not None and isinstance(max_width, int) and max_width > 0:
        print(f"[.] Генерация миниатюр: max_width = {max_width}px")
        _generate_thumbnails(media_src, media_thumbs_dst, max_width)
    else:
        print("[.] Миниатюры отключены — создаём пустую директорию")
        os.makedirs(media_thumbs_dst, exist_ok=True)

def _generate_thumbnails(src_dir: str, dst_dir: str, max_width: int):
    """Рекурсивно создаёт миниатюры (только для изображений) с суффиксом .thumb."""
    os.makedirs(dst_dir, exist_ok=True)
    for root, _, files in os.walk(src_dir):
        rel_path = os.path.relpath(root, src_dir)
        current_dst = os.path.join(dst_dir, rel_path) if rel_path != '.' else dst_dir
        os.makedirs(current_dst, exist_ok=True)

        for file in files:
            src_file = os.path.join(root, file)
            if is_image_file(file):
                # Формируем имя: basename.thumb.ext
                stem = Path(file).stem
                ext = Path(file).suffix
                thumb_filename = f"{stem}.thumb{ext}"
                dst_file = os.path.join(current_dst, thumb_filename)
                resize_image_if_needed(src_file, dst_file, max_width)
            # Не-фото НЕ копируются в thumbs/

def is_image_file(filename: str) -> bool:
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    return Path(filename).suffix.lower() in image_extensions

def copy_avatar_files(config: Dict[str, Any], output_dir: str):
    avatars_src = config.get('storage', {}).get('avatars_dir', 'avatars')
    avatars_dst = os.path.join(output_dir, 'avatars')
    if os.path.exists(avatars_src):
        if os.path.exists(avatars_dst):
            shutil.rmtree(avatars_dst)
        shutil.copytree(avatars_src, avatars_dst)
        print(f"[+] Скопированы аватары из '{avatars_src}' в '{avatars_dst}'")
    else:
        print(f"[!] Исходная директория аватаров не найдена: {avatars_src}")
