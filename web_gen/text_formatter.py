# web_gen/text_formatter.py
import re
from typing import Dict, List, Callable

class TelegramToHTMLConverter:
    def __init__(self):
        self.patterns = self._get_default_patterns()

    def _get_default_patterns(self) -> List[Dict]:
        """Возвращает список паттернов по умолчанию"""
        return [
            {
                'name': 'bold_italic',
                'pattern': r'\*\*__(.*?)__\*\*',
                'replacement': r'<b><i>\1</i></b>',
                'description': 'Жирный курсив',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'bold',
                'pattern': r'\*\*(.*?)\*\*',
                'replacement': r'<b>\1</b>',
                'description': 'Жирный текст',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'italic',
                'pattern': r'__(.*?)__',
                'replacement': r'<i>\1</i>',
                'description': 'Курсивный текст',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'strikethrough_bold',
                'pattern': r'~~\*\*(.*?)\*\*~~',
                'replacement': r'<s><b>\1</b></s>',
                'description': 'Зачеркнутый жирный текст',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'strikethrough',
                'pattern': r'~~(.*?)~~',
                'replacement': r'<s>\1</s>',
                'description': 'Зачеркнутый текст',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'inline_code',
                'pattern': r'`(.*?)`',
                'replacement': r'<code>\1</code>',
                'description': 'Моноширинный текст (inline code)',
                'flags': re.DOTALL # <-- Добавлен флаг
            },
            {
                'name': 'code_block',
                'pattern': r'```(.*?)```',
                'replacement': r'<pre><code>\1</code></pre>',
                'description': 'Блок кода',
                'flags': re.DOTALL
            },
            {
                'name': 'link',
                'pattern': r'\[(.*?)\]\((.*?)\)',
                'replacement': r'<a href="\2">\1</a>',
                'description': 'Ссылка'
                # link оставляем без DOTALL, так как в URL \n быть не должно
            }
        ]

    def add_pattern(self, name: str, pattern: str, replacement: str,
                   description: str = "", flags: int = 0) -> None:
        """Добавляет новый паттерн форматирования"""
        new_pattern = {
            'name': name,
            'pattern': pattern,
            'replacement': replacement,
            'description': description,
            'flags': flags
        }
        self.patterns.append(new_pattern)

    def remove_pattern(self, name: str) -> bool:
        """Удаляет паттерн по имени"""
        for i, pattern in enumerate(self.patterns):
            if pattern['name'] == name:
                self.patterns.pop(i)
                return True
        return False

    def get_patterns_info(self) -> List[Dict]:
        """Возвращает информацию о всех паттернах"""
        return [{'name': p['name'], 'description': p['description']}
                for p in self.patterns]

    def convert(self, text: str) -> str:
        """Конвертирует Telegram-форматирование в HTML"""
        if not text:
            return text

        result = text

        for pattern_config in self.patterns:
            pattern = pattern_config['pattern']
            replacement = pattern_config['replacement']
            flags = pattern_config.get('flags', 0)

            try:
                result = re.sub(pattern, replacement, result, flags=flags)
            except Exception as e:
                print(f"Ошибка при обработке паттерна {pattern_config['name']}: {e}")
                continue

        # Обработка переносов строк
        result = result.replace('\n', '<br>')

        return result

