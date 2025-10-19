# config.py
import yaml
from typing import Dict, Any

def load_config(path: str) -> Dict[str, Any]:
    """
    Загружает конфигурацию из YAML-файла.

    Args:
        path: Путь к файлу config.yaml.

    Returns:
        Словарь с конфигурацией.
    """
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# Опционально: можно добавить функцию валидации конфига
# def validate_config(config: Dict[str, Any]) -> bool:
#     # Проверки на наличие обязательных полей и их типов
#     required_keys = ['telegram', 'storage', 'site', 'ui']
#     for key in required_keys:
#         if key not in config:
#             print(f"Ошибка: Отсутствует обязательный ключ конфигурации: {key}")
#             return False
#     # ... другие проверки ...
#     return True
