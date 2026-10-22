"""Inventory candidate tracked release inputs without copying personal files.

This is an audit, not a public redistribution approval or an installer builder.
Run python -B tools/distribution/audit_payload.py. JSON is written to stdout.
"""
from pathlib import Path,PurePosixPath
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
ADDONS=('WFCore','WFStorage','WFStressProbe','WFDisplayTest')


def allowed(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:return False
    if len(path.parts)==3 and path.parts[0]=='addons' and path.parts[1] in ADDONS:
        return path.suffix in ('.lua','.toc','.xml','.md')
    if len(path.parts)==3 and path.parts[:2] in (('tools','qt_preview'),('tools','offline_preview')):
        return path.suffix=='.py' and not path.name.startswith(('test_','benchmark_','manual_'))
    return False


def audit(root=ROOT):
    root=Path(root).resolve(strict=True)
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
    result=[]
    for name in sorted(filter(allowed,tracked)):
        path=root.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Release input escapes the project: '+name)
        raw=path.read_bytes()
        result.append(dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    return {'stage':'source-audit-only','addons':list(ADDONS),'files':result,
            'excluded':'Personal saves, artwork/fonts, captures, third-party addons and catalogue data are not approved payloads.'}


if __name__=='__main__':print(json.dumps(audit(),indent=2))
