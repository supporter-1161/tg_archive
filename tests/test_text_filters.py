import os
import tempfile
import unittest

from web_gen.text_filters import load_rules, clean_text


class FilterRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.txt', delete=False)
        self.tmp.write('# комментарий\nКиберТопор — Подписаться\n\nПоддержи канал подпиской\n')
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_rules_skip_comments_and_empty_lines(self):
        rules = load_rules(self.tmp.name)
        self.assertEqual(rules, ('кибертопор — подписаться', 'поддержи канал подпиской'))

    def test_missing_file_gives_no_rules(self):
        self.assertEqual(load_rules('/nonexistent/filters.txt'), ())

    def test_empty_path_disables_rules(self):
        self.assertEqual(load_rules(''), ())


class CleanTextTest(unittest.TestCase):
    RULES = ('кибертопор — подписаться', 'поддержи канал подпиской', 'news max')

    def test_removes_ad_line_with_link(self):
        text = 'Полезный текст\n\n🕹[КиберТопор — Подписаться](https://t.me/+abc)'
        self.assertEqual(clean_text(text, self.RULES), 'Полезный текст')

    def test_case_insensitive(self):
        text = 'текст\n[ПОДДЕРЖИ КАНАЛ ПОДПИСКОЙ](https://t.me/x/1)'
        self.assertEqual(clean_text(text, self.RULES), 'текст')

    def test_removes_separator_lines(self):
        text = '================\n👁 [News max](https://max.ru/a) | 👁 [Soft max](https://max.ru/b)'
        self.assertEqual(clean_text(text, self.RULES), '')

    def test_separators_can_be_kept(self):
        text = 'до\n-------\nпосле'
        self.assertEqual(clean_text(text, (), remove_separators=False), text)

    def test_leaves_clean_text_untouched(self):
        text = 'строка 1\n\nстрока 2'
        self.assertIs(clean_text(text, self.RULES), text)

    def test_collapses_blank_lines_left_by_removed_blocks(self):
        text = 'начало\n\n-------\n👁 [News max](https://max.ru/a)\n-------\n\nконец'
        self.assertEqual(clean_text(text, self.RULES), 'начало\n\nконец')

    def test_empty_text(self):
        self.assertEqual(clean_text('', self.RULES), '')


if __name__ == '__main__':
    unittest.main()
