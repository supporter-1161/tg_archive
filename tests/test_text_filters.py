import os
import tempfile
import unittest

from web_gen.text_filters import load_rules, clean_text, normalize


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


class EmojiAndMarkupTest(unittest.TestCase):
    """Эмодзи и разметка не должны мешать совпадению."""

    def test_rule_with_emoji_matches_link_text(self):
        text = 'текст\n🕹[КиберТопор — Подписаться](https://t.me/+abc)'
        rules = (normalize('🕹КиберТопор — Подписаться'),)
        self.assertEqual(clean_text(text, rules), 'текст')

    def test_emoji_variation_selector_ignored(self):
        # в сообщении 🕹 (U+1F579), в словаре 🕹️ (U+1F579 U+FE0F)
        text = '🕹[КиберТопор](https://t.me/x)'
        rules = (normalize('🕹️КиберТопор'),)
        self.assertEqual(clean_text(text, rules), '')

    def test_bold_markup_does_not_break_match(self):
        text = '**Поддержи канал подпиской**'
        self.assertEqual(clean_text(text, (normalize('Поддержи канал подпиской'),)), '')

    def test_emoji_inside_rule_survives_when_no_match(self):
        text = 'Обычная новость 👁 про эмодзи'
        self.assertEqual(clean_text(text, (normalize('👁 News max'),)), text)


class LinkRulesTest(unittest.TestCase):
    """Ссылку можно ловить и по тексту, и по адресу."""

    LINE = '[**IT MEGA**](https://t.me/it_mega_g)'

    def assert_removed(self, rule):
        self.assertEqual(clean_text(self.LINE, (normalize(rule),)), '')

    def test_text_of_link(self):
        self.assert_removed('IT MEGA')

    def test_url_without_scheme(self):
        self.assert_removed('t.me/it_mega_g')

    def test_url_with_scheme(self):
        self.assert_removed('https://t.me/it_mega_g')

    def test_channel_slug(self):
        self.assert_removed('it_mega_g')

    def test_unrelated_text_kept(self):
        self.assertEqual(clean_text(self.LINE, (normalize('Kubernetes'),)), self.LINE)


if __name__ == '__main__':
    unittest.main()
