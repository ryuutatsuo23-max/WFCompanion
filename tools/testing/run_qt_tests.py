"""Run Qt tests together with deterministic widget teardown and hard time limits.

Closing a QWidget only hides it. Tests that retain hidden windows otherwise keep
timers and styles alive across cases, including when another case replaces the
application style. Keep one QApplication alive and destroy test widgets between
cases. The supervisor also bounds native-code stalls that Python cannot unwind.
"""
import argparse
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', action='append', help='Repeat to combine selected modules.')
    parser.add_argument('--test-dir', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'qt_preview')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--test-timeout', type=float, default=30)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0 or args.test_timeout <= 0:
        parser.error('Timeouts must be positive.')
    if not args.worker:
        env = dict(os.environ)
        env.setdefault('QT_QPA_PLATFORM', 'offscreen')
        command = [sys.executable, '-B', str(Path(__file__).resolve()),
                   '--worker',
                   '--test-dir', str(args.test_dir.resolve()),
                   '--test-timeout', str(args.test_timeout)]
        for pattern in args.pattern or ['test_*.py']:
            command += ['--pattern', pattern]
        with subprocess.Popen(command, env=env) as worker:
            try:
                return worker.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                # Windows venv launchers can own another Python process. Kill
                # only this worker tree, not other Python apps or previews.
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(worker.pid), '/T', '/F'],
                                   capture_output=True, timeout=10)
                if worker.poll() is None:
                    worker.kill()
                worker.wait(timeout=10)
                print('Qt test worker exceeded the suite timeout and was stopped.',
                      file=sys.stderr, flush=True)
                return 124

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)

    def clean_widgets(preserved=()):
        for widget in application.topLevelWidgets():
            if isValid(widget) and widget not in preserved:
                widget.hide()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if not QThreadPool.globalInstance().waitForDone(5000):
            raise RuntimeError('Qt background jobs survived test teardown.')

    class QtResult(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            # setUpClass runs before startTest. Keep its widgets through the
            # class's tests and tearDownClass, then destroy them via unittest's
            # class-cleanup hook. Only per-case widgets are removed below.
            self.preserved = set(application.topLevelWidgets())
            if getattr(self, 'fixture_class', None) is not type(test):
                type(test).addClassCleanup(clean_widgets)
                self.fixture_class = type(test)
            # Native watchdog exits even when Qt holds the GIL or spins in C++.
            faulthandler.dump_traceback_later(args.test_timeout, exit=True)

        def stopTest(self, test):
            try:
                # Test cleanup must not invoke close handlers that save or prompt.
                # Deferred deletion destroys children/timers with their owners.
                clean_widgets(self.preserved)
            except Exception:
                self.addError(test, sys.exc_info())
            finally:
                faulthandler.cancel_dump_traceback_later()
                super().stopTest(test)

    suite = unittest.TestSuite()
    for pattern in args.pattern or ['test_*.py']:
        suite.addTests(unittest.defaultTestLoader.discover(
            str(args.test_dir.resolve()), pattern=pattern))
    result = unittest.TextTestRunner(verbosity=2, resultclass=QtResult).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
