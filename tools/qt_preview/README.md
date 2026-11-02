
### Bounded combined Qt checks

Run `python -B tools/testing/run_qt_tests.py --timeout 1800 --test-timeout 90`
from the repository root. Repeat `--pattern test_name.py` to select several
modules while keeping them in one Qt process. The runner defaults to offscreen
rendering, retains one QApplication, and destroys hidden top-level test widgets
and their child timers after each case. Ordinary QWidget.close() only hides
windows; retaining them across application-style changes caused the previous
combined-run stalls/crash. Cleanup does not invoke application save/close prompts.
Windows created by setUpClass remain alive through tearDownClass and are then
destroyed using unittest's class-cleanup hook.

The per-case native watchdog includes teardown and prints a stack before exiting.
The suite supervisor also covers discovery and class setup; on Windows it stops
only its own worker process tree, including a virtual-environment launcher.
Timeouts fail the check. Verify both watchdogs and widget cleanup with
`python -B -m unittest discover -s tools/testing -p 'test_*.py' -v`.
These are test tools, excluded from the installed companion payload.

Addons transaction and recovery tests use temporary clients, package manifests
and account identities. The larger suite budget accommodates real interrupted
operations and filesystem fault checks; it does not change application deadlines
or turn a timed-out test into success. On Windows, symlink tests may skip without
the required privilege. Offscreen checks do not establish frozen Windows behavior.
