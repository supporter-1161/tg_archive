# web_gen/image_resizer.py
"""Превью для сайта: уменьшаем, но не раздуваем.

Старый код пересохранял даже те картинки, которые не нужно уменьшать, с
quality=95 — превью получалось тяжелее оригинала. Теперь маленькие файлы
просто копируются, а при ресайзе используется разумное сжатие.
"""
import os
import shutil

from PIL import Image

JPEG_QUALITY = 82


def resize_image_if_needed(input_path: str, output_path: str, max_width: int) -> None:
    if max_width <= 0:
        shutil.copy2(input_path, output_path)
        return

    try:
        with Image.open(input_path) as img:
            if img.width <= max_width:
                # Уменьшать нечего — отдаём оригинал как есть.
                shutil.copy2(input_path, output_path)
                return

            is_jpeg = output_path.lower().endswith(('.jpg', '.jpeg'))
            if is_jpeg and img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            elif img.mode == 'P' and not is_jpeg:
                img = img.convert('RGBA')

            ratio = max_width / img.width
            new_height = max(1, int(img.height * ratio))
            resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            if is_jpeg:
                resized.save(output_path, quality=JPEG_QUALITY,
                             optimize=True, progressive=True)
            elif output_path.lower().endswith('.png'):
                resized.save(output_path, optimize=True)
            else:
                resized.save(output_path)
    except Exception as e:
        print(f"[!] Ошибка при обработке изображения '{input_path}': {e}")
        # На случай ошибки — копируем оригинал, чтобы не ломать архив
        shutil.copy2(input_path, output_path)
