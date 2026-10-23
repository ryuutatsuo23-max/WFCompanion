"""Exercise Inno's upgrade file operations in an isolated app directory.

The production Files and addon cleanup directives are retained. OS registration,
shortcuts and post-install launches are disabled so a user's installed app stays
untouched. This validates file migration, not interactive wizard appearance.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile

from install_addons import package_metadata


def digest_tree(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def bundle_version(folder):
    module=ast.parse((folder/'_internal/payload/tools/qt_preview/release_updates.py').read_text(encoding='utf-8-sig'))
    return next(ast.literal_eval(node.value) for node in module.body
                if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets))


def verify(base, bundle, compiler, branding):
    source = Path(__file__).with_name('installer.iss')
    script = source.read_text(encoding='utf-8')
    # Restrict external side effects without replacing Inno's file migration.
    script = re.sub(r'(?ms)^\[Icons\].*?(?=^\[)', '', script)
    script = re.sub(r'(?ms)^\[Run\].*?(?=^\[)', '', script)
    script = '\n'.join(line for line in script.splitlines()
                       if not line.startswith('Type: files; Name:') or
                       'addons\\WFStorage\\README.md' in line)
    script = script.replace('AppId=WFCompanion', 'AppId=WFCompanion-IsolatedUpgradeCheck')
    script = script.replace('AppMutex=Local\\WFCompanion',
                            'Uninstallable=no\nCreateUninstallRegKey=no\nUsePreviousAppDir=no')
    with tempfile.TemporaryDirectory(prefix='wf-upgrade-check-') as tmp:
        work = Path(tmp).resolve()
        app = work/'app'
        shutil.copytree(base, app)
        obsolete = app/'_internal/payload/addons/WFStorage/README.md'
        obsolete.write_text('Old bundled README left by pre-0.1.23 installation.\n')
        try:
            package_metadata(app/'_internal/payload/addons', ['WFCore', 'WFStorage'])
        except ValueError as exc:
            assert 'pinned manifest' in str(exc), str(exc)
        else:
            raise AssertionError('Upgrade fixture must reproduce the manifest failure')
        protected = work/'personal'
        for relative in ('state/settings.json', 'game/WTF/save.lua',
                         'game/Interface/AddOns/WFStorage/README.md',
                         'game/Interface/AddOns/OtherAddon/main.lua'):
            path = protected/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Synthetic preserved content: '+relative)
        before = digest_tree(protected)
        marker = app/'keep-me.txt'
        marker.write_text('Unrelated file retained')
        iss = work/'upgrade.iss'
        iss.write_text(script, encoding='utf-8')
        subprocess.run([str(compiler), '/DPayload='+str(bundle), '/DVersion='+bundle_version(bundle),
                        '/DOutput='+str(work/'output'), '/DBranding='+str(branding), str(iss)],
                       check=True, stdout=subprocess.DEVNULL)
        expected = digest_tree(bundle)
        for attempt in range(2):
            subprocess.run([str(work/'output/WFCompanion-Setup.exe'), '/VERYSILENT',
                            '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/DIR='+str(app),
                            '/TYPE=companion', '/COMPONENTS=companion', '/TASKS=',
                            '/LOG='+str(work/f'install-{attempt}.log')], check=True,
                           timeout=120, creationflags=0x08000000)
            assert not obsolete.exists(), 'Obsolete bundled README survived upgrade'
            actual = digest_tree(app)
            assert all(actual.get(path) == digest for path, digest in expected.items())
            packages=json.loads((app/'_internal/payload/addon_packages.json').read_text(encoding='utf-8'))['packages']
            package_metadata(app/'_internal/payload/addons', list(packages))
            assert digest_tree(protected) == before
            assert marker.read_text() == 'Unrelated file retained'
        return dict(upgrade_from=bundle_version(base), upgrade_to=bundle_version(bundle), reproduced_old_manifest_failure=True,
                    upgrade_and_repeat_passed=True, bundle_files_verified=len(expected),
                    pinned_packages_valid=True, synthetic_personal_files_preserved=True,
                    scope='Inno file migration with OS integration disabled')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('base', 'bundle', 'compiler', 'branding', 'report'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    report = verify(*(p.resolve(strict=True) for p in
                      (args.base, args.bundle, args.compiler, args.branding)))
    args.report.resolve().write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
