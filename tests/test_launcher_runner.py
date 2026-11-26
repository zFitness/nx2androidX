"""The runner: the porter's stream of events, and where the porter is."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import runner   # noqa: E402


class Events(unittest.TestCase):
    def test_a_json_line_is_an_event(self):
        event = runner._event('{"ev": "say", "msg": "hello"}')
        self.assertEqual(event, {'ev': 'say', 'msg': 'hello'})

    def test_a_line_that_is_not_json_is_a_message(self):
        event = runner._event('something went wrong')
        self.assertEqual(event, {'ev': 'say', 'msg': 'something went wrong'})

    def test_an_empty_line_is_nothing(self):
        self.assertEqual(runner._event('   '), {})

    def test_a_json_value_that_is_not_an_object_is_a_message(self):
        event = runner._event('[1, 2, 3]')
        self.assertEqual(event['ev'], 'say')


class Porter(unittest.TestCase):
    def test_the_checkout_next_to_the_launcher_is_found(self):
        found = runner.porter_root()
        self.assertIsNotNone(found)
        self.assertTrue((found / 'porter' / 'phone_cli.py').is_file())

    def test_a_folder_with_a_porter_is_found(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'porter').mkdir()
            (Path(root) / 'porter' / 'phone_cli.py').write_text('', encoding='utf-8')
            self.assertEqual(runner.porter_root(root), Path(root))

    def test_a_folder_without_a_porter_falls_back_to_the_checkout(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(runner.porter_root(root), REPO)


class OneDocument(unittest.TestCase):
    def test_a_command_that_answers_nothing_is_a_message(self):
        document, code, error = runner.run_json(REPO, ['nosuchcommand'])
        self.assertIsNone(document)
        self.assertNotEqual(code, 0)
        self.assertTrue(error)

    def test_a_command_that_answers_something_that_is_not_json_is_a_message(self):
        document, code, error = runner.run_json(REPO, ['--help'])
        self.assertIsNone(document)
        self.assertTrue(error)


class Cancel(unittest.TestCase):
    """A port runs the rewriter and a compiler as children of its own, so a cancel has
    to reach the whole group."""

    def test_a_cancel_stops_the_process_and_its_children(self):
        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / 'porter'
            package.mkdir()
            (package / '__init__.py').write_text('', encoding='utf-8')
            (package / 'phone_cli.py').write_text(
                'import sys, time\n'
                'print(\'{"ev": "say", "msg": "working"}\', flush=True)\n'
                'time.sleep(120)\n', encoding='utf-8')
            porter = runner.Porter(Path(root))
            porter.start([])
            for _ in range(50):
                if not porter.events.empty():
                    break
                time.sleep(0.05)
            self.assertTrue(porter.running)
            porter.cancel()
            for _ in range(100):
                if not porter.running:
                    break
                time.sleep(0.05)
            self.assertFalse(porter.running, 'the cancel did not stop the process')


if __name__ == '__main__':
    unittest.main()
