"""Install only selected first-party addon code; preserve game saves and other addons."""
from pathlib import Path
from datetime import datetime
import csv
import hashlib
import json
import os
import shutil
import subprocess

ADDONS=('WFCore','WFStorage','WFStressProbe','WFDisplayTest')


def game_running():
    result=subprocess.run(['tasklist','/FI','IMAGENAME eq Wow.exe','/FO','CSV','/NH'],capture_output=True,text=True,check=True,creationflags=0x08000000)
    return any(row and row[0].lower()=='wow.exe' for row in csv.reader(result.stdout.splitlines()))


def safe_target(path,root):
    path=Path(path);root=Path(root).resolve(strict=True)
    if not path.resolve().is_relative_to(root):raise ValueError('Addon path escapes the selected game folder.')
    for parent in (path,*path.parents):
        if parent==root:break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):raise ValueError('Linked addon directories are not supported.')
    return path


def install(payload,client,selected,backup_root,*,check_game=True):
    client=Path(client).resolve(strict=True);payload=Path(payload).resolve(strict=True)
    if client.name not in ('_forever_','_classic_beta_') or not (client/'Wow.exe').is_file():raise ValueError('Select a Forever client folder containing Wow.exe.')
    selected=set(selected)
    if not selected or not selected<=set(ADDONS):raise ValueError('Select known Forever addons.')
    if 'WFStorage' in selected:selected.add('WFCore')
    if check_game and game_running():raise ValueError('Close WoW before installing addon updates.')
    jobs=[]
    for addon in sorted(selected):
        folder=payload/addon
        if not (folder/(addon+'.toc')).is_file():raise ValueError('Addon payload is incomplete: '+addon)
        for source in sorted(folder.iterdir()):
            if not source.is_file() or source.suffix not in ('.lua','.toc','.xml','.md'):raise ValueError('Unexpected addon payload file.')
            if source.is_symlink() or not source.resolve().is_relative_to(payload):raise ValueError('Linked payload files are not allowed.')
            target=safe_target(client/'Interface'/'AddOns'/addon/source.name,client)
            jobs.append((source,target,source.read_bytes()))
    backup=Path(backup_root).resolve()/datetime.now().strftime('%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True,exist_ok=False)
    before={target:(target.read_bytes() if target.exists() else None) for _,target,_ in jobs}
    for target,raw in before.items():
        if raw is not None:
            saved=backup/target.parent.name/target.name;saved.parent.mkdir(exist_ok=True);saved.write_bytes(raw)
            if saved.read_bytes()!=raw:raise ValueError('Addon backup verification failed.')
    written=[]
    try:
        for _,target,raw in jobs:
            safe_target(target,client)
            if (target.read_bytes() if target.exists() else None)!=before[target]:raise ValueError('Addon changed while preparing installation.')
            target.parent.mkdir(parents=True,exist_ok=True);written.append(target);target.write_bytes(raw)
            if target.read_bytes()!=raw:raise ValueError('Addon copy verification failed.')
    except Exception:
        for target in reversed(written):
            raw=before[target]
            safe_target(target,client)
            if raw is None:
                if target.is_file():target.unlink()
            else:target.write_bytes(raw)
        raise
    manifest={'client':str(client),'selected':sorted(selected),'files':[{ 'path':str(t.relative_to(client)), 'sha256':hashlib.sha256(raw).hexdigest()} for _,t,raw in jobs]}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest
