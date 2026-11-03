"""Reviewed-input bootstrap proposal. Never starts installers or the lifecycle harness.

The main entry point is hosted-only and requires a separately approved dispatch.
Importing this module performs no IO. Pure validators are tested locally with fixtures.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import zipfile

REPOSITORY = 'ryuutatsuo23-max/WFCompanion'
SOURCE = '99d50dd40b2eb9571c7619a8ae7fb9f1b3024e80'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def authenticate(path, expected):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked input')
    require(info.st_size == expected['size'] and sha(path) == expected['sha256'], 'input identity mismatch')


def write_record(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(len(raw) <= 5 * 1024 * 1024, 'record bound')
    with Path(path).open('xb') as stream:
        stream.write(raw)


def hosted_binding(env, plan, lane, approval_code, expected_revision):
    require(lane in ('fresh', 'replacement'), 'lane')
    require(env.get('GITHUB_ACTIONS') == 'true'
            and env.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and env.get('RUNNER_OS') == 'Windows'
            and env.get('GITHUB_REPOSITORY') == REPOSITORY
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_RUN_ATTEMPT') == '1', 'hosted first-attempt dispatch required')
    require(env.get('COMPUTERNAME', '').casefold() not in ('ryuu', 'drago2'), 'personal host')
    require(re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ID', '')) is not None, 'run identity')
    require(re.fullmatch(r'[0-9a-f]{40}', expected_revision or '') is not None
            and env.get('GITHUB_SHA') == expected_revision, 'workflow revision mismatch')
    require(env.get('GITHUB_REF') == 'refs/heads/' + plan['proposed_branch'], 'workflow branch mismatch')
    require(env.get('GITHUB_WORKFLOW_REF') == REPOSITORY + '/.github/workflows/windows-build.yml@refs/heads/'
            + plan['proposed_branch'], 'workflow path mismatch')
    require(approval_code == plan['plan_id'] and plan['source_commit'] == SOURCE, 'explicit dispatch approval mismatch')
    return {'schema': 1, 'execute_approved': True, 'repository': REPOSITORY,
            'source_commit': SOURCE, 'source_manifest_sha256': plan['capsule_manifest_sha256'],
            'run_id': env['GITHUB_RUN_ID'], 'invocation': plan['invocations'][lane], 'lane': lane,
            'scope': 'one separately authorized hosted attempt; exact plan ' + plan['plan_id']}


def checked_zip(path, limit, maximum_entries):
    """Read every entry/CRC with bounded counts and declared bytes, no general extraction."""
    files, directories, names, total = {}, set(), set(), 0
    with zipfile.ZipFile(path) as archive:
        require(len(archive.infolist()) <= maximum_entries, 'archive count bound')
        for entry in archive.infolist():
            name = entry.filename
            require(entry.orig_filename == name and '\\' not in entry.orig_filename,
                    'normalized archive path')
            parts = name.removesuffix('/').split('/')
            require(name and not name.startswith('/') and '\\' not in name and ':' not in name
                    and all(p not in ('', '.', '..') and not p.endswith((' ', '.')) for p in parts), 'unsafe archive path')
            require(name.casefold() not in names and not stat.S_ISLNK(entry.external_attr >> 16)
                    and not entry.flag_bits & 1, 'ambiguous archive entry')
            names.add(name.casefold())
            if entry.is_dir():
                require(entry.file_size == 0, 'directory payload')
                directories.add(name.rstrip('/'))
                continue
            total += entry.file_size
            require(total <= limit and entry.file_size <= limit, 'archive byte bound')
            raw = archive.read(entry)
            require(len(raw) == entry.file_size, 'archive size mismatch')
            files[name] = raw
    return files, directories


def verify_capsule(path, plan):
    authenticate(path, plan['capsule'])
    files, dirs = checked_zip(path, 5 * 1024 * 1024, 200)
    require(hashlib.sha256(files['SOURCE_MANIFEST.json']).hexdigest() == plan['capsule_manifest_sha256'], 'capsule manifest')
    manifest = json.loads(files['SOURCE_MANIFEST.json'])
    expected = {x['path']: x for x in manifest['files']}
    require(len(expected) == len(manifest['files']) and set(files) == set(expected) | {'SOURCE_MANIFEST.json'}
            and dirs == set(manifest['directories']) and len(dirs) == len(manifest['directories']), 'capsule membership')
    require(len(files) == 40 and len(dirs) == 46, 'capsule scope')
    for name, row in expected.items():
        require(len(files[name]) == row['size'] and hashlib.sha256(files[name]).hexdigest() == row['sha256'], 'capsule member digest')
    return files, dirs


def verify_ci_zip(path, plan):
    authenticate(path, plan['ci_zip'])
    files, dirs = checked_zip(path, 200 * 1024 * 1024, 20)
    expected = {x['path']: x for x in plan['ci_members']}
    require(set(files) == set(expected) and not dirs, 'CI artifact membership')
    for name, row in expected.items():
        require(len(files[name]) == row['size'] and hashlib.sha256(files[name]).hexdigest() == row['sha256'], 'CI member mismatch')
    require(files['source-commit.txt'].decode('utf-8-sig').strip() == SOURCE, 'CI source binding')
    raw = files[plan['candidate_member']]
    require(len(raw) == plan['installers']['candidate']['size']
            and hashlib.sha256(raw).hexdigest() == plan['installers']['candidate']['sha256'], 'CI installer binding')
    return raw


def github_command(arguments, destination, timeout, max_bytes, evidence):
    """Trusted runner gh only; binary stdout goes directly to an exclusive file, never text pipes."""
    executable = shutil.which('gh')
    require(executable is not None, 'GitHub CLI unavailable')
    error_path = destination.with_suffix(destination.suffix + '.stderr')
    with destination.open('xb') as output, error_path.open('xb') as errors:
        try:
            result = subprocess.run([executable, 'api', '--hostname', 'github.com', *arguments],
                                    stdout=output, stderr=errors, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            write_record(evidence / (destination.name + '.failure.json'), {'reason': 'acquisition timeout'})
            raise ValueError('acquisition timeout') from None
    # Raw tool diagnostics stay private inside the VM; bounded sanitized metadata is uploaded.
    require(result.returncode == 0, 'GitHub retrieval failure')
    require(destination.stat().st_size <= max_bytes and error_path.stat().st_size <= 1024 * 1024, 'acquisition output bound')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lane', choices=('fresh', 'replacement'), required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--approval-code', required=True)
    parser.add_argument('--expected-revision', required=True)
    args = parser.parse_args()
    require(platform.system() == 'Windows', 'Windows hosted preparation only')
    require(sha(args.plan) == args.plan_sha256, 'plan digest')
    plan = json.loads(args.plan.read_bytes())
    require(sha(__file__) == plan['bootstrap_sha256'], 'bootstrap digest')
    auth = hosted_binding(os.environ, plan, args.lane, args.approval_code, args.expected_revision)
    root = Path(os.environ['RUNNER_TEMP']) / ('wf-lifecycle-inputs-' + auth['invocation'])
    require(not root.exists(), 'fresh setup root required')
    root.mkdir(); evidence = root / 'evidence'; evidence.mkdir()
    start = time.monotonic()
    try:
        files, dirs = verify_capsule(args.plan.parent / 'execution-capsule.zip', plan)
        review = root / 'review'; review.mkdir()
        for name in sorted(dirs):
            (review / name).mkdir(parents=True, exist_ok=True)
        for name, raw in files.items():
            target = review / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            require(sha(target) == hashlib.sha256(raw).hexdigest(), 'capsule transfer')
        artifacts = root / 'artifacts'; artifacts.mkdir()
        metadata = root / 'release.json'
        github_command(['repos/' + REPOSITORY + '/releases/tags/v0.1.33'], metadata, 60, 1024 * 1024, evidence)
        release = json.loads(metadata.read_bytes())
        require(not release['draft'] and not release['prerelease'] and release['id'] == 423118148, 'release identity')
        assets = [x for x in release['assets'] if x['id'] == 673949668]
        require(len(assets) == 1 and assets[0]['size'] == plan['installers']['released']['size']
                and assets[0]['digest'] == 'sha256:' + plan['installers']['released']['sha256'], 'release declaration')
        metadata = root / 'ci-artifact.json'
        github_command(['repos/' + REPOSITORY + '/actions/artifacts/13188477478'], metadata, 60, 1024 * 1024, evidence)
        ci = json.loads(metadata.read_bytes())
        require(ci['id'] == 13188477478 and not ci['expired'] and ci['size_in_bytes'] == plan['ci_zip']['size']
                and ci['digest'] == 'sha256:' + plan['ci_zip']['sha256']
                and ci['workflow_run']['id'] == 41542477663 and ci['workflow_run']['head_sha'] == SOURCE, 'CI declaration drift')
        released = artifacts / plan['installers']['released']['file']
        github_command(['-H', 'Accept: application/octet-stream', 'repos/' + REPOSITORY + '/releases/assets/673949668'], released, 120, plan['installers']['released']['size'], evidence)
        authenticate(released, plan['installers']['released'])
        ci_zip = root / 'ci.zip'
        github_command(['repos/' + REPOSITORY + '/actions/artifacts/13188477478/zip'], ci_zip, 120, plan['ci_zip']['size'], evidence)
        candidate_bytes = verify_ci_zip(ci_zip, plan)
        candidate = artifacts / plan['installers']['candidate']['file']
        with candidate.open('xb') as stream:
            stream.write(candidate_bytes)
        authenticate(candidate, plan['installers']['candidate'])
        require(time.monotonic() - start < 540, 'setup budget exceeded')
        authorization = root / 'authorization.json'
        write_record(authorization, auth)
        receipt = {'schema': 1, 'lane': args.lane, 'invocation': auth['invocation'], 'run_id': auth['run_id'],
                   'workflow_revision': args.expected_revision, 'plan_sha256': args.plan_sha256,
                   'source_manifest_sha256': plan['capsule_manifest_sha256'],
                   'authorization_sha256': sha(authorization), 'installers': plan['installers'],
                   'image_os': os.environ.get('ImageOS'), 'image_version': os.environ.get('ImageVersion'),
                   'elapsed_seconds': time.monotonic() - start}
        write_record(evidence / 'setup.json', receipt)
        write_record(evidence / 'authorization.json', auth)
        write_record(root / 'prepared.json', {'root': str(root), 'review': str(review), 'artifacts': str(artifacts),
                     'authorization': str(authorization), 'authorization_sha256': sha(authorization)})
    except Exception as error:
        write_record(evidence / 'setup-failure.json', {'schema': 1, 'lane': args.lane,
                     'error_class': type(error).__name__, 'run_id': auth['run_id']})
        raise SystemExit('Hosted input preparation rejected; no installer was launched') from None


if __name__ == '__main__':
    main()
