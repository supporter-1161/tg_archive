"""Тесты группировки альбомов."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_gen.html_generator import HTMLGenerator  # noqa: E402


def msg(mid, gid=None):
    return {'id': mid, 'grouped_id': gid}


class GroupMessagesTest(unittest.TestCase):
    def test_single_messages_stay_separate(self):
        groups = HTMLGenerator.group_messages([msg(3), msg(2), msg(1)])
        self.assertEqual(len(groups), 3)
        self.assertFalse(any(g['is_album'] for g in groups))

    def test_album_is_grouped_and_sorted(self):
        groups = HTMLGenerator.group_messages([msg(12, 999), msg(11, 999), msg(10, 999), msg(9)])
        self.assertEqual(len(groups), 2)
        album = groups[0]
        self.assertTrue(album['is_album'])
        self.assertEqual([m['id'] for m in album['messages']], [10, 11, 12])
        self.assertFalse(groups[1]['is_album'])

    def test_lone_album_item_is_not_album(self):
        # Вторая половина альбома ушла на другую страницу
        groups = HTMLGenerator.group_messages([msg(5, 777)])
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]['is_album'])

    def test_two_different_albums(self):
        groups = HTMLGenerator.group_messages([
            msg(20, 1), msg(19, 1), msg(18, 2), msg(17, 2),
        ])
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(g['is_album'] for g in groups))


if __name__ == '__main__':
    unittest.main()
