# web_gen/file_copier.py
"""Копирование статики, медиа и аватаров в output/.

Копирование инкрементальное: файл переносится, только если его нет в output
или он изменился (размер + mtime). Каждый запуск `generate` больше не
перекладывает весь архив и не пересоздаёт все превью.
"""
import os
import shutil
from pathlib import Path
from typing import Dict, Any

from .image_resizer import resize_image_if_needed

THUMB_SUFFIX = '.thumb'


def _needs_copy(src: str, dst: str, compare_size: bool = True) -> bool:
    if not os.path.exists(dst):
        return True
    try:
        src_stat = os.stat(src)
        dst_stat = os.stat(dst)
    except OSError:
        return True
    if int(src_stat.st_mtime) > int(dst_stat.st_mtime):
        return True
    # Для превью размер заведомо отличается от оригинала — сверяем только mtime.
    return compare_size and src_stat.st_size != dst_stat.st_size


def _sync_tree(src_dir: str, dst_dir: str, transform=None, prune: bool = True) -> int:
    """Копирует дерево src -> dst, пропуская неизменившиеся файлы.

    ``transform(src, dst)`` может подменить обычное копирование (превью).
    Возвращает число обработанных (скопированных/пересозданных) файлов.
    """
    copied = 0
    expected = set()
    for root, _, files in os.walk(src_dir):
        rel_dir = os.path.relpath(root, src_dir)
        cur_dst = dst_dir if rel_dir == '.' else os.path.join(dst_dir, rel_dir)
        os.makedirs(cur_dst, exist_ok=True)
        for name in files:
            src_file = os.path.join(root, name)
            dst_name = name if transform is None else _thumb_name(name)
            if transform is not None and not is_image_file(name):
                continue
            dst_file = os.path.join(cur_dst, dst_name)
            rel = os.path.relpath(dst_file, dst_dir)
            expected.add(rel)
            if _needs_copy(src_file, dst_file, compare_size=transform is None):
                if transform is None:
                    shutil.copy2(src_file, dst_file)
                else:
                    transform(src_file, dst_file)
                copied += 1

    if prune and os.path.isdir(dst_dir):
        for root, dirs, files in os.walk(dst_dir, topdown=False):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), dst_dir)
                if rel not in expected:
                    os.remove(os.path.join(root, name))
            for name in dirs:
                path = os.path.join(root, name)
                if not os.listdir(path):
                    os.rmdir(path)
    return copied


def _thumb_name(filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    return f"{stem}{THUMB_SUFFIX}{ext}"


def copy_static_resources(static_src: str, output_dir: str):
    static_dst = os.path.join(output_dir, 'static')
    if not os.path.exists(static_src):
        print(f"[!] Исходная директория статики не найдена: {static_src}")
        return
    copied = _sync_tree(static_src, static_dst)
    print(f"[+] Статика синхронизирована ({copied} обновлено)")


def copy_media_files(config: Dict[str, Any], output_dir: str):
    media_src = config.get('storage', {}).get('media_dir', 'media')
    media_original_dst = os.path.join(output_dir, 'media', 'original')
    media_thumbs_dst = os.path.join(output_dir, 'media', 'thumbs')

    if not os.path.exists(media_src):
        print(f"[!] Исходная директория медиа не найдена: {media_src}")
        return

    copied = _sync_tree(media_src, media_original_dst)
    print(f"[+] Оригиналы синхронизированы ({copied} обновлено)")

    max_width = config.get('ui', {}).get('media_max_width', None)
    if isinstance(max_width, int) and max_width > 0:
        thumbs = _sync_tree(
            media_src, media_thumbs_dst,
            transform=lambda src, dst: resize_image_if_needed(src, dst, max_width),
        )
        print(f"[.] Превью синхронизированы: max_width={max_width}px ({thumbs} обновлено)")
    else:
        print("[.] Превью отключены (ui.media_max_width не задан)")


def is_image_file(filename: str) -> bool:
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    return Path(filename).suffix.lower() in image_extensions


def copy_avatar_files(config: Dict[str, Any], output_dir: str):
    avatars_src = config.get('storage', {}).get('avatars_dir', 'avatars')
    avatars_dst = os.path.join(output_dir, 'avatars')
    if not os.path.exists(avatars_src):
        print(f"[!] Исходная директория аватаров не найдена: {avatars_src}")
        return
    copied = _sync_tree(avatars_src, avatars_dst)
    print(f"[+] Аватары синхронизированы ({copied} обновлено)")
