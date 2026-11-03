"""Offline checkout/diagnostic regressions; never execute the lifecycle harness.

Run with --evidence-root NEW_DIRECTORY --pwsh EXISTING_PWSH. Test repositories,
synthetic files and command results are retained. Git is restricted to file://
transport; no source repository settings, accounts or permissions are changed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[2]
BASE = 'd6959a946af0930cdf624e04a7b31b45fef3df8f'
PATHS = ('.github/workflows/windows-build.yml',
         'tools/installer-lifecycle/prepare_hosted.py',
         'tools/installer-lifecycle/execution-plan.json',
         'tools/installer-lifecycle/execution-capsule.zip')
ROOT = None
PWSH = None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, *args):
    env = os.environ.copy()
    env.update(GIT_ALLOW_PROTOCOL='file', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL='NUL', GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['git', '-C', str(repo), *args], env=env,
                                   stderr=subprocess.STDOUT, timeout=30)


def body(workflow, lane):
    script = workflow['jobs'][lane]['steps'][2]['run']
    prefix = "$ErrorActionPreference='Stop'\n"
    assert script.startswith(prefix + 'function Assert-CheckoutBytes {\n')
    function, suffix = script[len(prefix):].split("$tool=Join-Path", 1)
    assert function.endswith('}\n')
    return function, '$tool=Join-Path' + suffix


class CheckoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads((REPO / PATHS[0]).read_bytes())
        cls.function, _ = body(cls.workflow, 'fresh')
        assert cls.function == body(cls.workflow, 'replacement')[0]
        cls.runner = ROOT / 'diagnostic-only.ps1'
        cls.runner.write_text(
            'param([string]$InputPath,[string]$Name,[string]$Hash,[long]$Size,\n'
            '      [string]$Mode="normal")\n$ErrorActionPreference="Stop"\n'
            + cls.function + '\n$locked=$null\ntry {\n'
            ' if($Mode -eq "locked"){$locked=[IO.File]::Open($InputPath,"Open","ReadWrite","None")}\n'
            ' Assert-CheckoutBytes -Path $InputPath -Name $Name -ExpectedHash $Hash -ExpectedSize $Size\n'
            ' [Console]::WriteLine("CHECK_PASSED")\n'
            '} finally {if($locked){$locked.Dispose()}}\n',
            encoding='utf-8', newline='\n')
        cls.serial = 0

    def probe(self, data, expected=None, size=None, name='prepare_hosted.py', mode='normal'):
        type(self).serial += 1
        case = ROOT / ('probe-' + str(type(self).serial).zfill(3))
        case.mkdir()
        path = case / 'private-synthetic-input'
        if data is not None:
            path.write_bytes(data)
        expected = expected if expected is not None else digest(data or b'')
        size = size if size is not None else len(data or b'')
        run = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-NonInteractive',
                              '-File', str(self.runner), '-InputPath', str(path),
                              '-Name', name, '-Hash', expected, '-Size', str(size),
                              '-Mode', mode], capture_output=True, timeout=15)
        (case / 'stdout.txt').write_bytes(run.stdout)
        (case / 'stderr.txt').write_bytes(run.stderr)
        (case / 'result.json').write_text(json.dumps({'exit_code': run.returncode,
                                                     'input_exists': path.exists()}), encoding='utf-8')
        stdout = run.stdout.decode('utf-8-sig')
        records = [line.removeprefix('WF_CHECKOUT_FAILURE ')
                   for line in stdout.splitlines() if line.startswith('WF_CHECKOUT_FAILURE ')]
        for record in records:
            self.assertLessEqual(len(record.encode()), 2048)
            self.assertNotIn(str(path), record)
        return run, [json.loads(record) for record in records]

    def rejected(self, *args, **kwargs):
        run, records = self.probe(*args, **kwargs)
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn(b'CHECK_PASSED', run.stdout)
        self.assertEqual(len(records), 1)
        return run, records[0]

    def seed(self, name, attributes):
        seed = ROOT / name
        seed.mkdir()
        git(seed, 'init', '--initial-branch=synthetic')
        git(seed, 'config', 'core.autocrlf', 'false')
        git(seed, 'config', 'core.hooksPath', str(ROOT / 'absent-hooks'))
        git(seed, 'config', 'user.name', 'Offline regression')
        git(seed, 'config', 'user.email', 'offline-regression@localhost')
        for path in PATHS:
            dest = seed / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((REPO / path).read_bytes())
        (seed / '.gitattributes').write_bytes(attributes)
        git(seed, 'add', '--', '.gitattributes', *PATHS)
        git(seed, 'commit', '-m', 'test: synthetic checkout inputs')
        return seed

    def checkout(self, seed, name, autocrlf, eol):
        target = ROOT / name
        git(ROOT, 'clone', '--no-local', '--no-hardlinks', '--no-checkout', str(seed), str(target))
        git(target, 'config', 'core.autocrlf', autocrlf)
        git(target, 'config', 'core.eol', eol)
        git(target, 'checkout', '--detach', 'HEAD')
        return target

    def test_legacy_windows_checkout_reproduces_both_failures(self):
        seed = self.seed('legacy-seed', git(REPO, 'show', BASE + ':.gitattributes'))
        target = self.checkout(seed, 'legacy-checkout', 'true', 'native')
        rows = []
        for path in PATHS[1:3]:
            blob = git(seed, 'show', 'HEAD:' + path)
            checked = (target / path).read_bytes()
            self.assertNotEqual(checked, blob)
            self.assertEqual(checked, blob.replace(b'\n', b'\r\n'))
            _, record = self.rejected(checked, digest(blob), len(blob), Path(path).name)
            self.assertEqual(record['observed_sha256'], digest(checked))
            self.assertEqual(record['crlf'], checked.count(b'\r\n'))
            rows.append({'path': path, 'blob_sha256': digest(blob),
                         'checkout_sha256': digest(checked), 'record': record})
        (ROOT / 'legacy-results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')

    def test_explicit_attributes_preserve_all_inputs_in_checkout_matrix(self):
        seed = self.seed('fixed-seed', (REPO / '.gitattributes').read_bytes())
        rows = []
        for i, (autocrlf, eol) in enumerate((('true', 'native'), ('false', 'native'),
                                            ('input', 'native'), ('false', 'crlf'))):
            with self.subTest(autocrlf=autocrlf, eol=eol):
                target = self.checkout(seed, f'fixed-checkout-{i}', autocrlf, eol)
                for path in PATHS:
                    blob = git(seed, 'show', 'HEAD:' + path)
                    checked = (target / path).read_bytes()
                    self.assertEqual(checked, blob)
                    rows.append({'autocrlf': autocrlf, 'eol': eol, 'path': path,
                                 'size': len(checked), 'sha256': digest(checked)})
                    if path != PATHS[0]:
                        run, records = self.probe(checked, name=Path(path).name)
                        self.assertEqual(run.returncode, 0)
                        self.assertEqual(records, [])
        (ROOT / 'checkout-matrix.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')

    def test_only_authentication_steps_change_in_workflow(self):
        before = json.loads(git(REPO, 'show', BASE + ':' + PATHS[0]))
        after = json.loads((REPO / PATHS[0]).read_bytes())
        for lane in ('fresh', 'replacement'):
            old = before['jobs'][lane]['steps'][2]['run']
            function, suffix = body(after, lane)
            self.assertIn('WF_CHECKOUT_FAILURE ', function)
            self.assertEqual(suffix.splitlines()[-2:], old.splitlines()[-2:])
            for path in PATHS[1:]:
                raw = (REPO / path).read_bytes()
                self.assertIn("-Name '" + Path(path).name + "'", suffix)
                self.assertIn("-ExpectedHash '" + digest(raw) + "'", suffix)
                self.assertIn('-ExpectedSize ' + str(len(raw)), suffix)
            after['jobs'][lane]['steps'][2]['run'] = old
        self.assertEqual(after, before)

    def test_existing_pinned_inputs_and_capsule_are_unchanged(self):
        for path in PATHS[1:]:
            self.assertEqual((REPO / path).read_bytes(), git(REPO, 'show', BASE + ':' + path))

    def test_corruption_and_wrong_size_are_rejected(self):
        self.rejected(b'changed', digest(b'original'), len(b'original'))
        self.rejected(b'same', digest(b'same'), 5)

    def test_mixed_newline_diagnostics_are_exact(self):
        data = b'one\r\ntwo\nthree\rfour'
        _, record = self.rejected(data, '0' * 64)
        self.assertEqual((record['lf'], record['crlf'], record['bare_cr']), (2, 1, 1))
        self.assertEqual(record['observed_bytes'], len(data))

    def test_diagnostics_do_not_disclose_source_or_private_values(self):
        secret = b'PRIVATE_CANARY_credential=C:/private/profile/auth-secret\n'
        run, record = self.rejected(secret, '0' * 64)
        self.assertNotIn(secret.strip(), run.stdout + run.stderr)
        self.assertEqual(set(record), {'schema', 'kind', 'file', 'reason', 'expected_sha256',
                                      'expected_bytes', 'observed_sha256', 'observed_bytes',
                                      'lf', 'crlf', 'bare_cr'})

    def test_missing_input_rejects_with_sanitized_diagnostic(self):
        _, record = self.rejected(None)
        self.assertEqual(record['reason'], 'read-failed')
        self.assertIsNone(record['observed_sha256'])

    def test_locked_input_rejects_and_is_released(self):
        _, record = self.rejected(b'synthetic', mode='locked')
        self.assertEqual(record['reason'], 'read-failed')
        path = ROOT / ('probe-' + str(type(self).serial).zfill(3)) / 'private-synthetic-input'
        with path.open('r+b') as stream:
            self.assertEqual(stream.read(), b'synthetic')

    def test_size_bound_prevents_unbounded_read(self):
        _, record = self.rejected(b'x' * (1048576 + 1), '0' * 64, 10)
        self.assertEqual(record['reason'], 'size-bound')
        self.assertIsNone(record['observed_sha256'])
        self.assertIsNone(record['lf'])

    def test_empty_file_can_only_pass_exact_size_and_digest(self):
        run, records = self.probe(b'')
        self.assertEqual(run.returncode, 0)
        self.assertEqual(records, [])
        self.rejected(b'', '0' * 64)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', required=True, type=Path)
    parser.add_argument('--pwsh', required=True)
    args, remaining = parser.parse_known_args()
    ROOT = args.evidence_root.resolve()
    if ROOT.exists() or ROOT.is_relative_to(REPO):
        raise SystemExit('Require a fresh evidence directory outside the source checkout')
    ROOT.mkdir(parents=False)
    PWSH = args.pwsh
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
