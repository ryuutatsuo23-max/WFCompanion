"""Offline harness checks. No account creation, frozen build or application launch."""
import ast
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from prepare_frozen_qualification import instrument_spec, inventory, zip_members
from qualification_payload import PHASES, content, require, snapshot, write_record, replace_attribute


class QualificationHarnessTests(unittest.TestCase):
    def test_spec_adds_test_entry_after_builtin_hooks_without_changing_launcher(self):
        source="a=Analysis(['launcher.py'],pathex=['payload'],hiddenimports=['install_addons'],runtime_hooks=[],excludes=['unsafe'])\npyz=PYZ(a.pure)\ne=EXE(pyz,a.scripts,name='WFCompanion')\n"
        original=ast.parse(source); changed=ast.parse(instrument_spec(source,Path('hook.py'),Path('harness')))
        call=changed.body[0].value
        values={k.arg:ast.literal_eval(k.value) for k in call.keywords}
        self.assertEqual(values['runtime_hooks'],[])
        self.assertEqual(ast.literal_eval(call.args[0]),['hook.py','launcher.py'])
        self.assertEqual(values['pathex'],['payload','harness'])
        self.assertEqual(values['hiddenimports'],['install_addons','qualification_payload'])
        for node in call.keywords:
            if node.arg in ('pathex','hiddenimports','runtime_hooks'):
                node.value=next(k.value for k in original.body[0].value.keywords if k.arg==node.arg)
        call.args[0]=original.body[0].value.args[0]
        self.assertEqual(ast.dump(original),ast.dump(changed))

    def test_ambiguous_or_unexpected_specs_reject(self):
        for source in ('x=1','a=Analysis();b=Analysis()',
                       "a=Analysis(pathex=[],hiddenimports=[],runtime_hooks=['old'])",
                       'a=Analysis(pathex=unknown,hiddenimports=[],runtime_hooks=[])'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                instrument_spec(source,Path('hook'),Path('harness'))

    def test_inventory_and_snapshot_detect_content_and_membership(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); path=root/'synthetic.txt'; path.write_bytes(b'first')
            before=inventory(root); detailed=snapshot(root)
            self.assertEqual(content(detailed)['synthetic.txt'][1],before['synthetic.txt']['sha256'])
            path.write_bytes(b'other')
            self.assertNotEqual(before,inventory(root))
            (root/'extra').write_bytes(b'')
            self.assertEqual(len(inventory(root)),2)

    def test_hardlinked_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'first').write_bytes(b'harmless')
            os.link(root/'first',root/'second')
            with self.assertRaises(ValueError):inventory(root)

    def test_record_is_exclusive_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'result.json'
            write_record(path,{'status':'passed'})
            with self.assertRaises(FileExistsError):write_record(path,{'status':'failed'})
            self.assertEqual(json.loads(path.read_bytes()),{'status':'passed'})
            with self.assertRaises(AssertionError):write_record(Path(temp)/'large',{'data':'x'*262144})
            self.assertFalse((Path(temp)/'large').exists())

    def test_zip_container_metadata_cannot_hide_member_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            paths=[Path(temp)/f'{i}.zip' for i in range(3)]
            for i,path in enumerate(paths):
                with zipfile.ZipFile(path,'w') as archive:
                    entry=zipfile.ZipInfo('module.pyc',(2020+i,1,1,0,0,0))
                    archive.writestr(entry,b'original' if i<2 else b'changed')
            self.assertNotEqual(paths[0].read_bytes(),paths[1].read_bytes())
            self.assertEqual(zip_members(paths[0]),zip_members(paths[1]))
            self.assertNotEqual(zip_members(paths[0]),zip_members(paths[2]))

    def test_assertion_cannot_silently_accept(self):
        with self.assertRaisesRegex(AssertionError,'sentinel'):require(False,'sentinel')
        require(True,'unused')

    def test_attribute_seam_restores_even_after_interruption(self):
        class Owner:
            value='original'
        for exception in (ValueError,KeyboardInterrupt):
            with self.assertRaises(exception):
                with replace_attribute(Owner,'value','injected'):
                    self.assertEqual(Owner.value,'injected')
                    raise exception()
            self.assertEqual(Owner.value,'original')

    def test_phase_list_is_bounded_and_explicit(self):
        self.assertEqual(len(PHASES),8)
        self.assertEqual(len(set(PHASES)),8)
        self.assertEqual(sum(p.startswith('interrupt-') for p in PHASES),2)

    def test_job_budget_covers_step_deadlines_and_preserves_evidence_uploads(self):
        workflow=(Path(__file__).resolve().parents[2]/'.github/workflows/windows-build.yml').read_text()
        job=workflow.split('\n  frozen-transactions:\n',1)[1]
        job_limit=int(re.search(r'^    timeout-minutes: (\d+)$',job,re.M)[1])
        steps=[int(value) for value in re.findall(r'^        timeout-minutes: (\d+)$',job,re.M)]
        self.assertEqual(steps,[5,10,12],'Per-step execution limits must not be relaxed')
        self.assertGreaterEqual(job_limit,sum(steps)+10,'Reserve setup/upload time outside the step budgets')
        self.assertLessEqual(job_limit,40,'The overall job must remain bounded')
        uploads=[step for step in job.split('      - name: ')[1:] if step.startswith('Preserve ')]
        self.assertEqual(len(uploads),2)
        for step in uploads:self.assertIn('\n        if: always()\n',step)

    def test_account_creation_is_behind_hosted_guard_and_no_password_arguments(self):
        root=Path(__file__).parent
        script=(root/'run_frozen_qualification.ps1').read_text()
        guard=script.index("throw 'Requires fresh standard GitHub-hosted Windows Server VM'")
        self.assertLess(guard,script.index('New-LocalUser'))
        self.assertIn("$start.Environment.Clear()",script)
        self.assertIn("$job.Assign($process)",script)
        self.assertLess(script.index('$job.Assign($process)'),script.index('$process.WaitForExit($remainingMs)'))
        self.assertIn('Administrator SID present, including deny-only',script)
        self.assertIn('$start.Password=$secure',script)
        self.assertNotIn('ArgumentList.Add($password)',script)
        self.assertNotIn('ArgumentList.Add($secure)',script)
        self.assertIn('$process.Kill()',script)
        self.assertGreater(script.index("throw 'Case disposal deadline exceeded'"),script.index('$job.Dispose()'))
        self.assertIn('Get-NetFirewallProfile',script)
        self.assertNotIn('network_blocked=$true',script)


if __name__=='__main__':unittest.main()
