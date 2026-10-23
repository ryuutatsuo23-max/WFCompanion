"""Regression checks for Qt cleanup and both watchdogs, using disposable tests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).with_name('run_qt_tests.py')


class RunnerTests(unittest.TestCase):
    def run_fixture(self, source, *options):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'test_fixture.py').write_text(source, encoding='utf-8')
            return subprocess.run(
                [sys.executable, '-B', str(RUNNER), '--test-dir', directory,
                 '--timeout', '20', *options], capture_output=True, text=True,
                timeout=30)

    def test_hidden_widget_and_timer_are_destroyed_between_cases(self):
        result = self.run_fixture('''
import unittest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
retained = []
class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = QWidget()
    @classmethod
    def tearDownClass(cls):
        assert isValid(cls.fixture)
        cls.fixture.close()
    def test_a_leave_hidden_widget(self):
        widget = QWidget()
        timer = QTimer(widget)
        timer.start(1)
        widget.close()
        retained.extend([widget, timer])
        self.assertTrue(isValid(widget))
    def test_b_no_previous_widgets_or_timers(self):
        self.assertTrue(retained)
        self.assertTrue(all(not isValid(item) for item in retained))
        self.assertTrue(isValid(self.fixture))
        self.assertEqual(QApplication.topLevelWidgets(), [self.fixture])
        QApplication.instance().setStyle('Windows')
class LaterCases(unittest.TestCase):
    def test_class_fixture_destroyed(self):
        self.assertFalse(isValid(Cases.fixture))
        self.assertEqual(QApplication.topLevelWidgets(), [])
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 3 tests', result.stderr)

    def test_blocked_case_exits_with_diagnostic(self):
        result = self.run_fixture('''
import time, unittest
class Cases(unittest.TestCase):
    def test_block(self): time.sleep(60)
''', '--test-timeout', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Timeout', result.stderr)
        self.assertIn('test_block', result.stderr)

    def test_blocked_discovery_is_stopped_by_supervisor(self):
        result = self.run_fixture('import time\ntime.sleep(60)\n', '--timeout', '2')
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn('suite timeout', result.stderr)


if __name__ == '__main__':
    unittest.main()
