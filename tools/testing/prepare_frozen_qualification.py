"""CI-only instrumentation build; never changes the public bundle or launcher."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked bundle entry')
        if path.is_file():
            if info.st_nlink != 1:
                raise ValueError('Hardlinked bundle entry')
            result[path.relative_to(root).as_posix()] = {'size': info.st_size, 'sha256': digest(path)}
    return result


def instrument_spec(source, hook, harness):
    tree = ast.parse(source)
    analyses = [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Analysis']
    if len(analyses) != 1:
        raise ValueError('Expected exactly one PyInstaller Analysis')
    scripts = analyses[0].args[0] if analyses[0].args else None
    if not isinstance(scripts, ast.List) or len(scripts.elts) != 1 or not isinstance(scripts.elts[0], ast.Constant):
        raise ValueError('Expected exactly one production entry script')
    # Multiple entry scripts run after PyInstaller's built-in runtime hooks.
    # A custom runtime_hooks entry would run BEFORE the Qt setup hook.
    scripts.elts.insert(0, ast.Constant(str(hook)))
    for name, extra in (('runtime_hooks', []), ('pathex', [str(harness)]),
                        ('hiddenimports', ['qualification_payload', 'unittest.mock'])):
        values = [value for value in analyses[0].keywords if value.arg == name]
        if len(values) != 1 or not isinstance(values[0].value, ast.List):
            raise ValueError('Unsupported specification field: ' + name)
        if name == 'runtime_hooks' and values[0].value.elts:
            raise ValueError('Unexpected existing runtime hooks')
        values[0].value.elts += [ast.Constant(value) for value in extra]
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.environ.get('RUNNER_OS') != 'Windows':
        raise RuntimeError('Only a standard GitHub-hosted Windows runner is supported')
    root = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if commit != os.environ['WF_TEST_COMMIT']:
        raise ValueError('Unexpected source commit')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root):
        raise ValueError('Modified tracked build inputs')
    stage = args.stage.resolve(strict=True)
    if not stage.is_relative_to(root / 'build'):
        raise ValueError('Unexpected build stage')
    original = stage / 'dist/WFCompanion'
    before = inventory(original)
    args.evidence.mkdir(parents=True, exist_ok=False)
    spec = stage / 'qualification.spec'
    with spec.open('x', encoding='utf-8') as out:
        out.write(instrument_spec((stage / 'WFCompanion.spec').read_text(encoding='utf-8'),
                                 Path(__file__).with_name('qualification_hook.py'), Path(__file__).parent))
    environment = dict(os.environ)
    environment['PATH'] = os.pathsep.join((str(Path(sys.executable).parent), sys.base_prefix,
        str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']))
    with (args.evidence / 'instrumentation-build.log').open('xb') as log:
        subprocess.run([sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(stage / 'qualification-dist'), '--workpath', str(stage / 'qualification-work'),
                        str(spec)], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    qualified = stage / 'qualification-dist/WFCompanion'
    after = inventory(qualified)
    if before != inventory(original):
        raise ValueError('Public bundle changed')
    # The tested production Python data and addon payload must remain byte-exact.
    payload = {key: value for key, value in before.items() if key.startswith('_internal/payload/')}
    if not payload or payload != {key: value for key, value in after.items() if key.startswith('_internal/payload/')}:
        raise ValueError('Instrumented build payload differs from public build')
    report = dict(schema=1, commit=commit, original=str(original), instrumented=str(qualified),
                  original_inventory=before, instrumented_inventory=after,
                  changed_bundle_paths=sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key)),
                  payload_identical=True, instrumentation='test-only runtime hook before unchanged production launcher',
                  harness={p.name:digest(p) for p in Path(__file__).parent.glob('qualification*.*') if p.is_file()})
    (args.evidence / 'build-binding.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'commit':commit, 'instrumented_executable_sha256':after['WFCompanion.exe']['sha256'],
                      'public_executable_sha256':before['WFCompanion.exe']['sha256'], 'payload_identical':True}))


if __name__ == '__main__':
    main()
