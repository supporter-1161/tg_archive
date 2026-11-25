# web_gen/text_formatter.py
"""Telegram-разметка -> безопасный HTML.

Важно: текст сообщения экранируется ДО применения markdown-паттернов.
Telegram отдаёт обычный текст, поэтому любой ``<script>`` в сообщении —
это попытка stored XSS на анонимном сайте. Наружу мы отдаём только те
теги, которые породили сами.
"""
import html
import re
from typing import Dict, List
from urllib.parse import urlparse

# Разрешённые схемы ссылок. javascript:/data:/vbscript: и прочее — отклоняем.
ALLOWED_LINK_SCHEMES = {'http', 'https', 'mailto'}


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
                'flags': re.DOTALL,
            },
            {
                'name': 'bold',
                'pattern': r'\*\*(.*?)\*\*',
                'replacement': r'<b>\1</b>',
                'description': 'Жирный текст',
                'flags': re.DOTALL,
            },
            {
                'name': 'italic',
                'pattern': r'__(.*?)__',
                'replacement': r'<i>\1</i>',
                'description': 'Курсивный текст',
                'flags': re.DOTALL,
            },
            {
                'name': 'strikethrough_bold',
                'pattern': r'~~\*\*(.*?)\*\*~~',
                'replacement': r'<s><b>\1</b></s>',
                'description': 'Зачеркнутый жирный текст',
                'flags': re.DOTALL,
            },
            {
                'name': 'strikethrough',
                'pattern': r'~~(.*?)~~',
                'replacement': r'<s>\1</s>',
                'description': 'Зачеркнутый текст',
                'flags': re.DOTALL,
            },
            {
                'name': 'code_block',
                'pattern': r'```(.*?)```',
                'replacement': r'<pre><code>\1</code></pre>',
                'description': 'Блок кода',
                'flags': re.DOTALL,
            },
            {
                'name': 'inline_code',
                'pattern': r'`(.*?)`',
                'replacement': r'<code>\1</code>',
                'description': 'Моноширинный текст (inline code)',
                'flags': re.DOTALL,
            },
        ]

    def add_pattern(self, name: str, pattern: str, replacement: str,
                    description: str = "", flags: int = 0) -> None:
        self.patterns.append({
            'name': name,
            'pattern': pattern,
            'replacement': replacement,
            'description': description,
            'flags': flags,
        })

    def remove_pattern(self, name: str) -> bool:
        for i, pattern in enumerate(self.patterns):
            if pattern['name'] == name:
                self.patterns.pop(i)
                return True
        return False

    def get_patterns_info(self) -> List[Dict]:
        return [{'name': p['name'], 'description': p['description']} for p in self.patterns]

    # --- конвертация -------------------------------------------------------

    def convert(self, text: str) -> str:
        if not text:
            return text

        # 1. Экранируем всё пользовательское содержимое.
        result = html.escape(text)

        # 2. Разметка Telegram.
        for pattern_config in self.patterns:
            try:
                result = re.sub(
                    pattern_config['pattern'],
                    pattern_config['replacement'],
                    result,
                    flags=pattern_config.get('flags', 0),
                )
            except Exception as e:
                print(f"Ошибка при обработке паттерна {pattern_config['name']}: {e}")

        # 3. Ссылки — со схемным allowlist'ом.
        result = self._convert_links(result)

        # 4. Переносы строк.
        return result.replace('\n', '<br>')

    @staticmethod
    def _convert_links(text: str) -> str:
        """[текст](url) -> <a>, только для http/https/mailto."""

        def replace(match: re.Match) -> str:
            label, raw_url = match.group(1), match.group(2).strip()
            parsed = urlparse(html.unescape(raw_url))
            if parsed.scheme.lower() not in ALLOWED_LINK_SCHEMES:
                return match.group(0)
            return (f'<a href="{raw_url}" target="_blank" '
                    f'rel="noopener noreferrer nofollow">{label}</a>')

        return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', replace, text)
