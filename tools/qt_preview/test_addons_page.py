from pathlib import Path
import tempfile
import unittest
import os
import hashlib
import json
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from companion import Companion
from addons_page import AddonsPage


@unittest.skipUnless(os.name=='nt','Windows transaction publication and locks')
class AddonsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        # Isolation precedes every host constructor, including its default page.
        isolation=tempfile.TemporaryDirectory();self.addCleanup(isolation.cleanup)
        self.installation_anchor=Path(isolation.name).resolve()/'local-app-data'
        self.installation_anchor.mkdir()
        from addon_installation_context import WindowsUserContext
        env=patch.dict(os.environ,LOCALAPPDATA=str(self.installation_anchor))
        env.start();self.addCleanup(env.stop)
        context=patch('addon_installation_configuration.current_windows_context',side_effect=lambda:WindowsUserContext(
            'S-1-5-21-1-2-3-1001',self.installation_anchor,False,1))
        context.start();self.addCleanup(context.stop)
        empty_client=Path(isolation.name)/'_forever_'
        for target,kwargs in (
            ('game_folder_picker.standard_roots',dict(return_value=[])),
            ('game_data_review.CLIENT',dict(new=empty_client)),
            ('probe_report.CLIENT',dict(new=empty_client)),
            ('probe_report.ReportReader.__init__.__defaults__',dict(new=(empty_client,))),
            ('update_panel.Updates.auto_check',{}),
            ('saved_character_connection.SavedCharacterConnection.restore',{}),
            ('saved_character_connection.SavedCharacterConnection.poll',{}),
            ('game_data_monitor.GameDataMonitor.poll',{}),
            ('first_run.show_if_needed',{})):
            guard=patch(target,**kwargs);guard.start();self.addCleanup(guard.stop)
        # Closed Qt windows otherwise survive between tests and accumulate widgets.
        existing=set(self.app.topLevelWidgets())
        def dispose_windows():
            for window in self.app.topLevelWidgets():
                if window not in existing:window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.addCleanup(dispose_windows)

    @staticmethod
    def authenticate_payload(payload):
        packages={}
        for folder in payload.iterdir():
            packages[folder.name]=dict(version='synthetic',source_commit='a'*40,archive_sha256='b'*64,
                files={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in folder.rglob('*') if p.is_file()})
        (payload.parent/'addon_packages.json').write_text(json.dumps(dict(schema=1,packages=packages)))

    def test_shared_backend_lock_reports_busy_without_installing(self):
        from install_addons import installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client=root/'_forever_';client.mkdir();(client/'Wow.exe').touch()
            payload=root/'package';source=payload/'WFCore';source.mkdir(parents=True)
            (source/'WFCore.toc').write_bytes(b'toc')
            self.authenticate_payload(payload)
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop();host.saved_character_connection.timer.stop()
            try:
                page=AddonsPage(host,payload=payload,clients=[client])
                with installation_lock(client):page.install_selected('WFCore')
                self.assertIn('Another addon operation',page.transaction_status.text())
                self.assertNotIn(str(root),page.notice.text())
                self.assertFalse((client/'Interface').exists())
                self.assertFalse((root/'state/AddonBackups').exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.install_selected('WFCore')
                self.assertEqual(page.core_status.text(),'Installed · matches bundled package')
            finally:host.close();self.app.processEvents()

    def test_hard_linked_destination_blocks_install_and_explains_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client=root/'_forever_';client.mkdir();(client/'Wow.exe').touch()
            payload=root/'package';source=payload/'WFCore';source.mkdir(parents=True)
            (source/'WFCore.toc').write_bytes(b'toc');(source/'Core.lua').write_bytes(b'new')
            self.authenticate_payload(payload)
            target=client/'Interface/AddOns/WFCore/Core.lua';target.parent.mkdir(parents=True);target.write_bytes(b'original')
            sentinel=root/'external-sentinel.lua'
            try:os.link(target,sentinel)
            except OSError as exc:
                if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Hard links unavailable: Windows error '+str(exc.winerror))
                raise
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop();host.saved_character_connection.timer.stop()
            try:
                page=AddonsPage(host,payload=payload,clients=[client])
                self.assertFalse(page.core_action.isEnabled())
                self.assertIn('Hard-linked addon file',page.details.text())
                self.assertIn('independent addon copy',page.details.text())
                self.assertNotIn(str(root),page.entry_errors['Forever Core'])
                with patch('install_addons.install') as install,patch.object(QMessageBox,'question') as question:
                    page.install_selected('WFCore');install.assert_not_called();question.assert_not_called()
                self.assertEqual(target.read_bytes(),b'original');self.assertEqual(sentinel.read_bytes(),b'original')
                self.assertTrue(os.path.samefile(target,sentinel))
                self.assertFalse((root/'state/AddonBackups').exists())
            finally:host.close();self.app.processEvents()

    def test_failed_install_reports_complete_or_incomplete_rollback(self):
        import install_addons as engine
        for incomplete in (False,True):
            with self.subTest(incomplete=incomplete),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();client=root/'_forever_';client.mkdir();(client/'Wow.exe').touch()
                payload=root/'package';source=payload/'WFCore';source.mkdir(parents=True)
                target=client/'Interface/AddOns/WFCore';target.mkdir(parents=True)
                for name in ('a.lua','b.lua','WFCore.toc'):
                    (source/name).write_bytes(b'new');(target/name).write_bytes(b'old')
                self.authenticate_payload(payload)
                host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop();host.saved_character_connection.timer.stop()
                try:
                    page=AddonsPage(host,payload=payload,clients=[client])
                    history=page.transactions.configuration.standard/'AddonBackups'
                    previous=set(history.glob('transaction-*/WFCore/b.lua'))
                    replace=engine.os.replace;failed=False
                    def replacing(stage,destination):
                        nonlocal failed
                        if Path(destination)==target/'b.lua':
                            if not failed:
                                failed=True;raise OSError('Synthetic installation failure')
                        if incomplete and failed and Path(destination)==target/'a.lua':
                            raise OSError('Synthetic rollback failure')
                        return replace(stage,destination)
                    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as question,patch.object(engine.os,'replace',replacing):
                        page.install_selected('WFCore')
                    question.assert_called_once()
                    notice=page.notice.text()
                    self.assertTrue(failed)
                    self.assertNotIn(str(root),notice);self.assertNotIn('Installed Forever',notice)
                    if incomplete:
                        self.assertIn('explicit recovery',notice)
                        self.assertFalse(page.core_action.isEnabled())
                        self.assertTrue((client/engine.PENDING_NAME).exists())
                    else:
                        self.assertIn('restored and rollback finalized',notice)
                        self.assertTrue(page.core_action.isEnabled())
                        self.assertFalse((client/engine.PENDING_NAME).exists())
                    self.assertEqual((target/'a.lua').read_bytes(),b'new' if incomplete else b'old')
                    self.assertEqual((target/'b.lua').read_bytes(),b'old')
                    self.assertEqual((target/'WFCore.toc').read_bytes(),b'old')
                    backups=list(set(history.glob('transaction-*/WFCore/b.lua'))-previous)
                    self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),b'old')
                finally:host.close();self.app.processEvents()

    def test_install_backup_repair_and_remembered_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').write_bytes(b'fixture')
            payload=root/'package'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('fixture '+name)
            self.authenticate_payload(payload)
            # First transactional installation may replace explicitly confirmed
            # legacy files; it preserves the old code and unrelated user state.
            target=client/'Interface/AddOns/WFStorage/WFStorage.toc'
            target.parent.mkdir(parents=True);target.write_text('local modification')
            save=client/'WTF/saved.lua';save.parent.mkdir();save.write_bytes(b'personal')
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                host.show_page('Addons');self.assertEqual(host.page_picker.currentText(),'Addons')
                page=AddonsPage(host,payload=payload,clients=[client])
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):page.install_selected()
                self.assertEqual(target.read_text(),'local modification')
                with patch('install_addons.game_running',return_value=True) as running,patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
                    page.install_selected();running.assert_not_called()
                self.assertEqual(page.status.text(),'Installed · matches bundled package')
                self.assertFalse(page.action.isEnabled());self.assertEqual(save.read_bytes(),b'personal')
                backups=list((page.transactions.configuration.standard/'AddonBackups').glob('transaction-*/WFStorage/WFStorage.toc'))
                self.assertTrue(any(p.read_text()=='local modification' for p in backups))
                reopened=AddonsPage(host,payload=payload,clients=[])
                self.assertEqual(reopened.client.resolve(),client.resolve())
                self.assertEqual(save.read_bytes(),b'personal')
                self.assertIsNone(host.addons_page.payload)
                self.assertFalse(host.addons_page.action.isEnabled())
                # Settled history permits a fresh, explicitly confirmed repair.
                target.write_text('later edit');page.refresh()
                before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in [target,save,*backups]}
                self.assertTrue(page.action.isEnabled())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    page.install_selected();question.assert_called_once()
                self.assertEqual(question.call_args.args[1],'Replace addon files?')
                self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
                self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before})
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as question:
                    page.install_selected();question.assert_called_once()
                self.assertEqual(target.read_bytes(),(payload/'WFStorage/WFStorage.toc').read_bytes())
                copies=list((page.transactions.configuration.standard/'AddonBackups').glob('transaction-*/WFStorage/WFStorage.toc'))
                self.assertEqual(sorted(p.read_text() for p in copies),['later edit','local modification'])
                self.assertEqual(save.read_bytes(),b'personal')
                self.assertEqual(page.status.text(),'Installed · matches bundled package')
                self.assertFalse(page.action.isEnabled())
            finally:host.close();self.app.processEvents()

    def test_professions_entry_installs_dependency_without_storage(self):
        import hashlib,json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'package/addons';packages={}
            for name in ('WFCore','WFStorage','WFProfessions'):
                folder=payload/name;folder.mkdir(parents=True);toc=folder/(name+'.toc');toc.write_text('## Version: 0.7.0\n')
                packages[name]=dict(version='test',source_commit='a'*40,archive_sha256='b'*64,files={toc.name:hashlib.sha256(toc.read_bytes()).hexdigest()})
            (payload.parent/'addon_packages.json').write_text(json.dumps(dict(schema=1,packages=packages)))
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop();host.saved_character_connection.timer.stop()
            try:
                page=AddonsPage(host,payload=payload,clients=[client])
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.core_action.click()
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as question:
                    page.professions_action.click();question.assert_called_once()
                self.assertIn('WFCore, WFProfessions',question.call_args.args[2])
                self.assertEqual(page.professions_status.text(),'Installed · matches bundled package')
                self.assertFalse(page.professions_action.isEnabled())
                self.assertFalse((client/'Interface/AddOns/WFStorage').exists())
                self.assertIn('WFProfessions',page.details.text());self.assertIn('WFStorage',page.details.text())
                target=client/'Interface/AddOns/WFProfessions/WFProfessions.toc'
                self.assertEqual(target.read_bytes(),(payload/'WFProfessions/WFProfessions.toc').read_bytes())
                reopened=AddonsPage(host,payload=payload,clients=[])
                self.assertFalse(reopened.professions_action.isEnabled())
            finally:host.close();self.app.processEvents()

    def test_ambiguous_clients_require_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clients=[root/'_forever_',root/'_classic_beta_']
            for client in clients:client.mkdir();(client/'Wow.exe').touch()
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                page=AddonsPage(host,clients=clients)
                self.assertIsNone(page.client);self.assertIn('Multiple clients',page.picker.notice.text())
            finally:host.close();self.app.processEvents()

    def test_core_installs_independently_and_storage_keeps_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'package'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('fixture '+name)
            self.authenticate_payload(payload)
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                page=AddonsPage(host,payload=payload,clients=[client])
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.core_action.click()
                self.assertTrue((client/'Interface/AddOns/WFCore/WFCore.toc').is_file())
                self.assertFalse((client/'Interface/AddOns/WFStorage').exists())
                self.assertFalse(page.core_action.isEnabled());self.assertTrue(page.action.isEnabled())
                self.assertEqual(page.status.text(),'Ready to install missing files')
                self.assertEqual(page.action.text(),'Install Forever Storage')
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    page.action.click()
                    question.assert_called_once()
                self.assertFalse((client/'Interface/AddOns/WFStorage/WFStorage.toc').exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.action.click()
                self.assertTrue((client/'Interface/AddOns/WFStorage/WFStorage.toc').is_file())
                self.assertFalse(page.action.isEnabled())
                self.assertFalse(page.core_action.isEnabled())
                # A missing Storage file must not hide a real Core conflict.
                (client/'Interface/AddOns/WFStorage/WFStorage.toc').unlink()
                core=client/'Interface/AddOns/WFCore/WFCore.toc'
                core.write_text('locally modified Core')
                page.refresh()
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    page.action.click()
                    question.assert_called_once()
                self.assertEqual(question.call_args.args[1],'Replace addon files?')
                self.assertIn('may be newer or locally modified',question.call_args.args[2])
                self.assertIn('Addons: WFCore, WFStorage',question.call_args.args[2])
                self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
                self.assertEqual(core.read_text(),'locally modified Core')
                self.assertFalse((client/'Interface/AddOns/WFStorage/WFStorage.toc').exists())
            finally:host.close();self.app.processEvents()
