import shutil
import os
from typing import Dict, Any

def copy_static_resources(static_src: str, output_dir: str):
    """Копирует статические ресурсы (CSS, JS и т.д.) в output_dir."""
    static_dst = os.path.join(output_dir, 'static')
    if os.path.exists(static_src):
        if os.path.exists(static_dst):
            shutil.rmtree(static_dst)
            print(f"[.] Удалена старая директория статики: {static_dst}")
        shutil.copytree(static_src, static_dst)
        print(f"[+] Скопированы статические ресурсы из '{static_src}' в '{static_dst}'")
    else:
        print(f"[!] Исходная директория статики не найдена: {static_src}")

def copy_media_files(config: Dict[str, Any], output_dir: str):
    """Копирует медиафайлы в output_dir."""
    media_src = config.get('storage', {}).get('media_dir', 'media')
    media_dst = os.path.join(output_dir, 'media')
    if os.path.exists(media_src):
        if os.path.exists(media_dst):
            shutil.rmtree(media_dst)
            print(f"[.] Удалена старая директория медиа: {media_dst}")
        shutil.copytree(media_src, media_dst)
        print(f"[+] Скопированы медиафайлы из '{media_src}' в '{media_dst}'")
    else:
        print(f"[!] Исходная директория медиа не найдена: {media_src}")

def copy_avatar_files(config: Dict[str, Any], output_dir: str):
    """Копирует аватары пользователей в output_dir."""
    avatars_src = config.get('storage', {}).get('avatars_dir', 'avatars')
    avatars_dst = os.path.join(output_dir, 'avatars')
    if os.path.exists(avatars_src):
        if os.path.exists(avatars_dst):
            shutil.rmtree(avatars_dst)
            print(f"[.] Удалена старая директория аватаров: {avatars_dst}")
        shutil.copytree(avatars_src, avatars_dst)
        print(f"[+] Скопированы аватары из '{avatars_src}' в '{avatars_dst}'")
    else:
        print(f"[!] Исходная директория аватаров не найдена: {avatars_src}")

