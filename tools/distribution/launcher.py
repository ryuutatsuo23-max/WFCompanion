"""Bundled entry point: resources read from the bundle, saves stored per user."""
from pathlib import Path
import argparse
import ctypes
import os
import sys


def main():
    bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'payload'
    sys.path.insert(0,str(bundle/'tools'/'offline_preview'))
    sys.path.insert(0,str(bundle/'tools'/'qt_preview'))
    state=Path(os.environ['LOCALAPPDATA'])/'WoWForever'/'Companion'
    parser=argparse.ArgumentParser();parser.add_argument('--install-addons');parser.add_argument('--addons');parser.add_argument('--smoke-test',type=Path)
    args=parser.parse_args()
    if args.install_addons:
        from install_addons import install
        try:install(bundle/'addons',args.install_addons,(args.addons or '').split(','),state/'AddonBackups');return 0
        except Exception as exc:
            state.mkdir(parents=True,exist_ok=True);(state/'addon-install-error.txt').write_text(str(exc));return 1
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\WFCompanion')
    if ctypes.windll.kernel32.GetLastError()==183:return 0
    from companion import Companion,QApplication
    application=QApplication(sys.argv)
    from PySide6.QtGui import QIcon
    application.setWindowIcon(QIcon(str(bundle/'branding'/'forever.ico')))
    try:
        directory=args.smoke_test.resolve() if args.smoke_test else state
        directory.mkdir(parents=True,exist_ok=True)
        window=Companion(directory)
        if args.smoke_test:
            window.testing=True;window.updates_panel.timer.stop();window.character_overview.game_data_monitor.set_enabled(False)
            window.show();application.processEvents();window.grab().save(str(directory/'smoke.png'))
            window.close();(directory/'smoke-ok.txt').write_text('Bundled companion opened successfully.');return 0
        window.show();return application.exec()
    finally:ctypes.windll.kernel32.CloseHandle(mutex)


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        import traceback
        location=Path(os.environ['LOCALAPPDATA'])/'WoWForever'/'Companion'
        if '--smoke-test' in sys.argv:location=Path(sys.argv[sys.argv.index('--smoke-test')+1]).resolve()
        location.mkdir(parents=True,exist_ok=True);(location/'startup-error.txt').write_text(traceback.format_exc())
        raise SystemExit(1)
