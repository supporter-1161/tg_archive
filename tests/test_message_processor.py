"""Тесты вспомогательной логики MessageProcessor, не требующие сети."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.message_processor import MessageProcessor  # noqa: E402


class SkippedSizeTest(unittest.TestCase):
    def make_processor(self, limit_mb):
        limit = limit_mb * 1024 * 1024 if limit_mb else None
        return MessageProcessor(api_client=None, db_path=':memory:', max_media_size_bytes=limit)

    def make_message(self, size):
        return SimpleNamespace(id=1, file=SimpleNamespace(size=size, name='a.7z', ext='.7z'))

    def test_big_file_skipped(self):
        proc = self.make_processor(50)
        self.assertEqual(proc.skipped_size(self.make_message(120 * 1024 ** 2)), 120 * 1024 ** 2)

    def test_small_file_not_skipped(self):
        proc = self.make_processor(50)
        self.assertIsNone(proc.skipped_size(self.make_message(10 * 1024 ** 2)))

    def test_no_limit(self):
        proc = self.make_processor(0)
        self.assertIsNone(proc.skipped_size(self.make_message(5 * 1024 ** 3)))

    def test_no_file(self):
        proc = self.make_processor(50)
        self.assertIsNone(proc.skipped_size(SimpleNamespace(id=1, file=None)))


if __name__ == '__main__':
    unittest.main()
