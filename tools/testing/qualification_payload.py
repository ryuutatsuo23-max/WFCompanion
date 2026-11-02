"""Frozen-only synthetic scenarios. Never collected into the public application.

UI responses and fault points are scripted; native account/configuration checks,
package authentication, transaction locks, writes and recovery are NOT mocked.
"""
import ctypes
from contextlib import contextmanager
from ctypes import wintypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


PHASES = ('positive', 'interrupt-recovery', 'recover', 'reporting',
          'interrupt-changed', 'reject-changed', 'unsafe', 'lock')


@contextmanager
def replace_attribute(owner, name, value):
    """Test seams only; avoids unittest.mock importing extra frozen dependencies."""
    previous = getattr(owner,name)
    setattr(owner,name,value)
    try:
        yield
    finally:
        setattr(owner,name,previous)


def reporting_fault(*args, **kwargs):
    raise OSError('synthetic reporting interruption')


def forbidden_mutation(*args, **kwargs):
    raise AssertionError('Unexpected reinstall or restoration')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def write_record(path, value):
    raw = json.dumps(value, ensure_ascii=True, indent=2).encode('utf-8')
    require(len(raw) <= 256 * 1024, 'Oversized evidence')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        require(not path.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Linked fixture')
        if path.is_file():
            require(info.st_size < 8 * 1024 * 1024, 'Oversized fixture')
            result[path.relative_to(root).as_posix()] = {
                'size':info.st_size, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'mtime_ns':info.st_mtime_ns, 'device':info.st_dev, 'inode':info.st_ino}
    return result


def content(records):
    return {name:(value['size'], value['sha256']) for name,value in records.items()}


def native_token(expected_sid):
    # Independent of the controller's native token query and production provider.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    token = wintypes.HANDLE()
    require(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)), 'Token open failed')
    try:
        values = {}
        for label, kind in (('elevated',20), ('elevation_type',18), ('session',12)):
            value = wintypes.DWORD(); length = wintypes.DWORD()
            require(advapi.GetTokenInformation(token,kind,ctypes.byref(value),4,ctypes.byref(length)), 'Token query failed')
            values[label] = value.value
        require(values['elevated'] == 0 and values['elevation_type'] == 1 and values['session'] > 0,
                'Not an interactive standard-user token')
    finally:
        require(kernel.CloseHandle(token), 'Token close failed')
    from addon_installation_context import current_windows_context, validate_context
    context = validate_context(current_windows_context(), intended_sid=expected_sid)
    require(not context.elevated, 'Production account gate rejected')
    values['sid'] = context.sid
    values['known_folder_matches_environment'] = os.path.normcase(str(context.local_app_data)) == os.path.normcase(os.environ['LOCALAPPDATA'])
    require(values['known_folder_matches_environment'], 'Known folder/environment mismatch')
    return values


def run(root, phase, request, report):
    import install_addons as engine
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QThread
    import game_folder_picker
    from companion import Companion
    from addon_operation_status import OperationStatus

    report['token'] = native_token(request['sid'])
    report['modules'] = {}
    for name in ('install_addons','addon_installation_context','addon_installation_configuration',
                 'addon_installation_service','addon_installation_gui','addon_operation_status',
                 'addons_page','addon_recovery_dialog'):
        module = importlib.import_module(name)
        require(Path(module.__file__).resolve().is_relative_to(Path(sys._MEIPASS).resolve()), 'Source-tree import')
        report['modules'][name] = str(Path(module.__file__).relative_to(sys._MEIPASS))
    report['checks'].append('frozen_modules_and_native_identity')
    key = 'recovery' if phase in ('interrupt-recovery','recover') else 'changed' if phase in ('interrupt-changed','reject-changed') else phase
    area = root / 'cases' / key
    client = area / '_forever_'
    payload = Path(sys._MEIPASS) / 'payload/addons'
    names = ('WFCore','WFStorage','WFProfessions')
    metadata = engine.package_metadata(payload,names)
    require(set(metadata) == set(names), 'Bundled package declaration')
    managed = [path for name in names for path in engine.package_files(payload,name)]
    original_relative = next(p.relative_to(payload) for p in managed if p.suffix == '.lua' and p.parent.name == 'WFCore')
    original_file = client / 'Interface/AddOns' / original_relative
    original_bytes = b'-- ORIGINAL synthetic addon; never game code\n'
    if phase not in ('recover','reject-changed'):
        client.mkdir(parents=True, exist_ok=False)
        (client/'Wow.exe').write_bytes(b'WF Companion synthetic client; not executable\n')
        original_file.parent.mkdir(parents=True)
        original_file.write_bytes(original_bytes)
        unrelated = client/'Interface/AddOns/SyntheticOther/keep.txt'
        unrelated.parent.mkdir(); unrelated.write_bytes(b'preserve unrelated synthetic file\n')
        (area/'baseline.json').write_text(json.dumps(snapshot(client)), encoding='utf-8')
    require((client/'Wow.exe').read_bytes() == b'WF Companion synthetic client; not executable\n', 'Client marker')
    baseline = json.loads((area/'baseline.json').read_text(encoding='utf-8'))
    app = QApplication.instance() or QApplication([])
    # Only discovery input is narrowed. No transaction authority is injected.
    with replace_attribute(game_folder_picker,'standard_roots',lambda:[client]):
        host = Companion(area/'ui-state')
    host.testing = True
    host.updates_panel.timer.stop()
    host.saved_character_connection.timer.stop()
    host.character_overview.game_data_monitor.set_enabled(False)
    host.show(); app.processEvents()
    page = host.addons_page
    try:
        require(page.transactions is not None, 'Default transaction factory unavailable')
        require(page.remember_client(client) and page.client == client, 'Synthetic client selection')
        report['checks'].append('real_qt_companion_addons_and_client_selection')
        config = page.transactions.configuration
        prompts = []
        def question(*args):
            prompts.append(args[2])
            require(args[-1] == QMessageBox.StandardButton.Cancel, 'Unsafe confirmation default')
            return QMessageBox.StandardButton.Yes
        def install(addon='WFStorage', accept=True):
            prompts.clear()
            with replace_attribute(QMessageBox,'question',question if accept else lambda *a: (prompts.append(a[2]) or QMessageBox.StandardButton.Cancel)):
                page.install_selected(addon)
        def installed(selected):
            expected = {p.relative_to(payload).as_posix():(p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest())
                        for p in managed if p.relative_to(payload).parts[0] in selected}
            actual = content(snapshot(client/'Interface/AddOns'))
            require(all(actual.get(p) == value for p,value in expected.items()), 'Installed payload mismatch')
            require(set(actual) == set(expected) | {'SyntheticOther/keep.txt'}, 'Unexpected installed file')
            report['installed_files_verified'] = len(expected)
        def recover(action):
            dialog = page.review_recovery(); require(dialog is not None,'Recovery dialog unavailable')
            button = {'rollback':dialog.restore_action, 'report':dialog.report_action}[action]
            require(button.isEnabled(), 'Expected recovery action unavailable')
            with replace_attribute(QMessageBox,'question',question):
                dialog.resolve(action)
            require(not page._transaction_warnings, 'Unresolved recovery warning')
            dialog.reject()

        if phase == 'positive':
            before = snapshot(client)
            install(accept=False)
            require(snapshot(client) == before and not (client/engine.PENDING_NAME).exists(), 'Cancel mutated client')
            require(len(prompts) == 1, 'Missing install confirmation')
            for value in (str(client),str(client/'Interface/AddOns'),str(config.standard/'AddonBackups'),'WFCore','WFStorage'):
                require(value in prompts[0], 'Incorrect confirmation binding')
            report['checks'] += ['confirmation_paths_dependencies_backup','cancel_preserves_bytes_identity_timestamps']
            install(); require('installation and retained backups verified' in page.notice.text(), 'Storage install rejected')
            installed(('WFCore','WFStorage'))
            copies = list((config.standard/'AddonBackups').glob('transaction-*/'+original_relative.as_posix()))
            require(any(p.read_bytes()==original_bytes for p in copies), 'Original backup absent')
            install('WFProfessions'); require('verified' in page.notice.text(), 'Professions install rejected')
            installed(names)
            require(not (client/engine.PENDING_NAME).exists(), 'Unresolved installation marker')
            require('matches bundled' in page.status.text() and 'matches bundled' in page.professions_status.text(), 'UI status not refreshed')
            report['checks'] += ['storage_with_core_dependency','verified_original_backup','professions_and_exact_complete_payload','refreshed_status']
        elif phase.startswith('interrupt-'):
            original_replace = engine.os.replace
            def stop_after_write(source,target):
                value = original_replace(source,target)
                if str(source).endswith('.stage') and Path(target).is_relative_to(client/'Interface/AddOns'):
                    require((client/engine.PENDING_NAME).is_file(), 'Crash before durable pending evidence')
                    report['checks'].append('actual_frozen_process_exit_after_replacement')
                    report['expected_interruption'] = True
                    write_record(root/'results'/f'{phase}.json',report)
                    os._exit(73)  # Deliberate process death: no Python rollback/finally.
                return value
            with replace_attribute(engine.os,'replace',stop_after_write):install()
            raise AssertionError('Interruption point not reached')
        elif phase in ('recover','reject-changed'):
            require((client/engine.PENDING_NAME).is_file(), 'Interrupted evidence missing')
            require(not page.action.isEnabled(), 'Pending transaction allowed new install')
            before = snapshot(client)
            install(); require(snapshot(client)==before,'Blocked install mutated client')
            report['checks'].append('interrupted_evidence_blocks_new_install')
            if phase == 'recover':
                recover('rollback')
                require(content(snapshot(client/'Interface/AddOns')) ==
                        {p.removeprefix('Interface/AddOns/'): (v['size'],v['sha256']) for p,v in baseline.items() if p.startswith('Interface/AddOns/')}, 'Originals not restored exactly')
                require(not (client/engine.PENDING_NAME).exists(), 'Recovery marker remains')
                report['checks'].append('fresh_frozen_process_verified_originals_restored')
            else:
                recovery_root = engine.production_recovery_root(client)
                pending = engine.inspect_pending_transaction(client,recovery_root)
                # Find an actual original in the retained transaction backup, never invent evidence.
                copies = list((config.standard/'AddonBackups').glob('transaction-*/'+original_relative.as_posix()))
                matching = [p for p in copies if p.read_bytes()==original_bytes]
                require(matching and pending['state']=='valid', 'No valid recovery backup to corrupt')
                # Recovery uses prepare-* evidence; use its validated record location instead.
                originals = list(recovery_root.glob('prepare-*/'+original_relative.as_posix()))
                require(len(originals)==1, 'Ambiguous recovery originals')
                originals[0].write_bytes(b'changed synthetic recovery evidence')
                before = snapshot(client)
                dialog = page.review_recovery(); dialog.check_again()
                require(not dialog.restore_action.isEnabled() and not dialog.finish_action.isEnabled(), 'Changed evidence accepted')
                install(); require(snapshot(client)==before,'Changed evidence caused mutation')
                report['checks'].append('changed_recovery_evidence_rejected')
                dialog.reject()
        elif phase == 'reporting':
            with replace_attribute(OperationStatus,'reported',reporting_fault):
                install()
            installed(('WFCore','WFStorage'))
            require(not (client/engine.PENDING_NAME).exists(), 'Not a finish-reporting outcome')
            before = snapshot(client/'Interface/AddOns'); backups = snapshot(config.standard/'AddonBackups')
            with replace_attribute(engine,'_execute_transaction_locked',forbidden_mutation), \
                 replace_attribute(engine,'_recover_pending_locked',forbidden_mutation):
                recover('report')
            require(snapshot(client/'Interface/AddOns')==before and snapshot(config.standard/'AddonBackups')==backups, 'Finish reporting changed files')
            report['checks'].append('finish_reporting_without_reinstall_restore_or_backup_changes')
        elif phase == 'unsafe':
            link = area/'synthetic-hardlink'; os.link(original_file,link)
            before = snapshot(client)
            page.refresh(); install()
            require(not page.action.isEnabled() and snapshot(client)==before, 'Hardlinked destination accepted')
            require(link.read_bytes()==original_bytes, 'Hardlink sentinel changed')
            try: engine.safe_target(client/'../escape',client,for_write=True)
            except ValueError: pass
            else: raise AssertionError('Unsafe path accepted')
            report['checks'].append('hardlink_and_unsafe_path_rejected')
        elif phase == 'lock':
            ready=threading.Event(); release=threading.Event(); errors=[]
            def hold():
                try:
                    with engine._transaction_client_lock(client):
                        ready.set(); require(release.wait(20),'Lock-holder deadline')
                except BaseException as exc:errors.append(type(exc).__name__)
            worker=threading.Thread(target=hold); worker.start()
            try:
                require(ready.wait(5),'Native lock not acquired')
                before=snapshot(client)
                result=page.transactions.service.install(payload,client,['WFStorage'])
                require(result.category=='busy' and snapshot(client)==before,'Client contention not rejected')
            finally:
                release.set(); worker.join(5)
            require(not worker.is_alive() and not errors,'Lock-holder cleanup failed')
            report['checks'].append('in_process_contention_while_native_client_mutex_held')
        require((client/'Wow.exe').read_bytes()==b'WF Companion synthetic client; not executable\n','Synthetic executable sentinel changed')
        require((client/'Interface/AddOns/SyntheticOther/keep.txt').read_bytes()==b'preserve unrelated synthetic file\n','Unrelated synthetic addon changed')
    finally:
        host.close(); app.processEvents()
        require(not any(t.isRunning() for t in host.findChildren(QThread)), 'Qt worker remains running')
        require(threading.active_count()==1,'Python worker remains running')
        report['checks'].append('qt_closed_and_workers_stopped')


def main():
    # No source-mode fallback, no arbitrary script argument and no credentials.
    if not getattr(sys,'frozen',False) or os.name!='nt' or os.environ.get('WF_FROZEN_CI')!='1':
        os._exit(90)
    if len(sys.argv)!=4 or sys.argv[1]!='--wf-qualification' or sys.argv[3] not in PHASES:
        os._exit(91)
    root=Path(sys.argv[2]).resolve(strict=True); phase=sys.argv[3]
    if root.parent!=Path('C:/') or not root.name.startswith('wf-frozen-ci-'):
        os._exit(92)
    payload=Path(sys._MEIPASS)/'payload'
    sys.path[:0]=[str(payload/'tools/qt_preview'),str(payload/'tools/offline_preview')]
    request=json.loads((root/'request.json').read_text(encoding='utf-8-sig'))
    report=dict(schema=1,phase=phase,pid=os.getpid(),commit=request['commit'],invocation=request['invocation'],
                frozen=True,exe_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),checks=[])
    started=time.monotonic()
    try:
        require(report['exe_sha256']==request['exe_sha256'],'Executable binding mismatch')
        run(root,phase,request,report)
        report['status']='passed'; code=0
    except BaseException as exc:
        report['status']='failed'; report['exception']=type(exc).__name__
        report['frames']=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                          for frame in traceback.extract_tb(exc.__traceback__)[-12:]]
        if isinstance(exc,AssertionError):report['assertion']=str(exc)[:240]
        code=1
    report['elapsed_seconds']=time.monotonic()-started
    write_record(root/'results'/f'{phase}.json',report)
    # The test-only hook owns termination; normal production launcher is unchanged.
    os._exit(code)
