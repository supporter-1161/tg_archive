# web_gen/image_resizer.py
import os
from PIL import Image

def resize_image_if_needed(input_path: str, output_path: str, max_width: int) -> None:
    """
    Открывает изображение из input_path, масштабирует его по ширине до max_width (с сохранением пропорций),
    если текущая ширина больше max_width, и сохраняет результат в output_path.
    Если ширина <= max_width — копирует исходник без изменений.
    
    Поддерживаемые форматы: jpg, jpeg, png, webp (всё, что PIL умеет читать/писать).
    """
    if max_width <= 0:
        # Если лимит отключён — просто копируем
        import shutil
        shutil.copy2(input_path, output_path)
        return

    try:
        with Image.open(input_path) as img:
            # Автоматически конвертируем palette-изображения (например, GIF) в RGB для корректного сохранения в JPEG/PNG
            if img.mode in ("P", "RGBA"):
                # Для прозрачности в PNG оставляем RGBA, для JPEG — RGB
                if output_path.lower().endswith(('.jpg', '.jpeg')):
                    img = img.convert("RGB")
                else:
                    # PNG/WebP могут поддерживать прозрачность
                    img = img.convert("RGBA") if img.mode == "P" else img

            original_width = img.width

            if original_width <= max_width:
                # Нет нужды ресайзить — копируем как есть
                img.save(output_path, quality=95)  # качество для JPEG
            else:
                # Вычисляем новую высоту с сохранением пропорций
                ratio = max_width / original_width
                new_height = int(img.height * ratio)
                resized_img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                resized_img.save(output_path, quality=95)

    except Exception as e:
        print(f"[!] Ошибка при обработке изображения '{input_path}': {e}")
        # На случай ошибки — всё равно копируем оригинал, чтобы не ломать архив
        import shutil
        shutil.copy2(input_path, output_path)
