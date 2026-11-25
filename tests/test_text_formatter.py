"""Тесты конвертера разметки: экранирование и безопасные ссылки."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_gen.text_formatter import TelegramToHTMLConverter  # noqa: E402


class ConverterTest(unittest.TestCase):
    def setUp(self):
        self.conv = TelegramToHTMLConverter()

    def test_script_is_escaped(self):
        out = self.conv.convert('<script>alert(1)</script>')
        self.assertNotIn('<script', out)
        self.assertIn('&lt;script&gt;', out)

    def test_img_onerror_escaped(self):
        out = self.conv.convert('<img src=x onerror=alert(1)>')
        self.assertNotIn('<img', out)
        self.assertIn('&lt;img', out)

    def test_markdown_still_works(self):
        self.assertEqual(self.conv.convert('**жирно**'), '<b>жирно</b>')
        self.assertEqual(self.conv.convert('__курсив__'), '<i>курсив</i>')
        self.assertEqual(self.conv.convert('`code`'), '<code>code</code>')

    def test_newlines(self):
        self.assertEqual(self.conv.convert('a\nb'), 'a<br>b')

    def test_http_link_allowed(self):
        out = self.conv.convert('[сайт](https://example.com/a?b=1&c=2)')
        self.assertIn('<a href="https://example.com/a?b=1&amp;c=2"', out)
        self.assertIn('rel="noopener noreferrer nofollow"', out)
        self.assertIn('>сайт</a>', out)

    def test_javascript_link_rejected(self):
        out = self.conv.convert('[клик](javascript:alert(1))')
        self.assertNotIn('<a ', out)
        self.assertIn('javascript:alert(1)', out)

    def test_data_link_rejected(self):
        out = self.conv.convert('[x](data:text/html;base64,PHNjcmlwdD4=)')
        self.assertNotIn('<a ', out)

    def test_html_inside_bold_is_escaped(self):
        out = self.conv.convert('**<b>не тег</b>**')
        self.assertNotIn('<b>не тег</b>', out)
        self.assertIn('&lt;b&gt;', out)


if __name__ == '__main__':
    unittest.main()
