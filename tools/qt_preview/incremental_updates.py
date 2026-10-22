"""Optional exact-base patches. Any uncertainty falls back to the full installer.

Trust is the same as the existing updater: fixed GitHub HTTPS release assets and
SHA-256, not a publisher signature. No downloaded metadata is executed as code.
"""
from pathlib import Path
import hashlib
import json
import re
import sys
import release_updates as releases


def matches(root,metadata):
    root=Path(root).resolve(strict=True)
    rows=metadata.get('files')
    if not isinstance(rows,dict) or not 1<=len(rows)<=5000 or 'WFCompanion.exe' not in rows:return False
    seen=set()
    for name,row in rows.items():
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./ +\-]+',name):return False
        parts=name.split('/')
        if any(x in ('','.','..') or x.endswith((' ','.')) for x in parts):return False
        if any(re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',x) for x in parts):return False
        if name!='WFCompanion.exe' and not name.startswith('_internal/'):return False
        if name.lower() in seen:return False
        seen.add(name.lower())
        if not isinstance(row,dict) or type(row.get('size')) is not int or not 0<=row['size']<=releases.MAX_INSTALLER:return False
        if not isinstance(row.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',row['sha256']):return False
        path=root
        for part in parts:
            path=path/part
            if path.is_symlink() or path.is_junction():return False
        if not path.is_file() or path.stat().st_size!=row['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:return False
    return True


def select(release,root):
    patch=release.get('patch')
    if not patch:return release
    try:
        url,size=patch['metadata']
        expected=f'https://github.com/{releases.REPOSITORY}/releases/download/{release["version"]}/WFCompanion-patch-from-{patch["base"]}.json'
        if url!=expected:return release
        with releases.request(url) as stream:raw=stream.read(2_000_001)
        if len(raw)!=size or len(raw)>2_000_000:return release
        data=json.loads(raw)
        if data.get('schema')!=1 or data.get('base')!=patch['base'] or data.get('target')!=release['version'].removeprefix('v'):return release
        if data.get('asset')!=patch['asset'] or data.get('size')!=patch['installer'][1] or not re.fullmatch('[a-f0-9]{64}',str(data.get('sha256'))):return release
        if patch['installer'][1]>=release['installer'][1] or not matches(root,data):return release
        return dict(version=release['version'],asset=patch['asset'],installer=patch['installer'],checksum=patch['checksum'],sha256=data['sha256'])
    except (OSError,ValueError,KeyError,TypeError):return release


def fetch(release,directory,progress=None):
    directory=Path(directory)
    chosen=release
    if getattr(sys,'frozen',False) and not (directory/'full-update-required').exists():
        chosen=select(release,Path(sys.executable).parent)
    try:return releases.download(chosen,directory,progress)
    except (OSError,ValueError):
        if chosen is release:raise
        return releases.download(release,directory,progress)
