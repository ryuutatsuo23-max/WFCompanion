"""Install only selected first-party addon code; preserve game saves and other addons."""
from pathlib import Path
from datetime import datetime
import csv
import hashlib
import json
import os
import shutil
import subprocess
import re
import sys

ADDONS=('WFCore','WFStorage','WFProfessions','WFStressProbe','WFDisplayTest')
PINNED_ADDONS={'WFCore','WFStorage','WFProfessions'}


def package_metadata(payload,selected):
    path=Path(payload).parent/'addon_packages.json'
    if not path.exists():
        if (getattr(sys,'frozen',False) and set(selected)&PINNED_ADDONS) or 'WFProfessions' in selected:raise ValueError('Pinned addon package manifest is missing.')
        return {}  # Development fixtures only.
    document=json.loads(path.read_text(encoding='utf-8'))
    if document.get('schema')!=1 or not isinstance(document.get('packages'),dict):raise ValueError('Invalid addon package manifest.')
    result={}
    for addon in sorted(set(selected)&PINNED_ADDONS):
        info=document['packages'].get(addon)
        if not isinstance(info,dict) or not re.fullmatch('[a-f0-9]{40}',str(info.get('source_commit'))) or not re.fullmatch('[a-f0-9]{64}',str(info.get('archive_sha256'))):
            raise ValueError('Missing pinned addon identity.')
        actual={p.relative_to(Path(payload)/addon).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in package_files(payload,addon)}
        if actual!=info.get('files'):raise ValueError('Addon package differs from its pinned manifest: '+addon)
        result[addon]=info
    return result


def check_legacy(client):
    toc=safe_target(Path(client)/'Interface/AddOns/WFCore/WFCore.toc',client)
    if not toc.exists():return
    text=toc.read_text(encoding='utf-8-sig')
    if re.search(r'^##\s*Version:\s*0\.6(?:\.|\s|$)',text,re.M|re.I) or re.search(r'^\s*(?:Bags|BankUI|InventoryUI)\.lua\s*$',text,re.M|re.I):
        raise ValueError('Older combined Core installation detected. A separate migration is required; no files changed.')


def game_running():
    result=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,check=True,creationflags=0x08000000)
    return any(row and row[0].lower() in ('wow.exe','wowb.exe') for row in csv.reader(result.stdout.splitlines()))


def safe_target(path,root):
    path=Path(path);root=Path(root).resolve(strict=True)
    if not path.resolve().is_relative_to(root):raise ValueError('Addon path escapes the selected game folder.')
    for parent in (path,*path.parents):
        if parent==root:break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):raise ValueError('Linked addon directories are not supported.')
    return path


def validate_client(client):
    client=Path(client).resolve(strict=True)
    if client.name not in ('_forever_','_classic_beta_') or not any((client/name).is_file() for name in ('Wow.exe','WowB.exe')):
        raise ValueError('Select a Forever client folder containing Wow.exe or WowB.exe.')
    return client


def package_files(payload,addon):
    """Only reviewed runtime/docs and each addon's named branding assets."""
    payload=Path(payload).resolve(strict=True)
    folder=safe_target(payload/addon,payload)
    if not (folder/(addon+'.toc')).is_file():raise ValueError('Addon payload is incomplete: '+addon)
    files=[]
    for source in sorted(folder.iterdir()):
        safe_target(source,payload)
        if source.is_dir():
            if addon not in ('WFStorage','WFProfessions') or source.name!='branding':raise ValueError('Unexpected addon payload directory.')
            for asset in source.iterdir():
                safe_target(asset,payload)
                if not asset.is_file():raise ValueError('Unexpected addon branding file.')
                raw=asset.read_bytes()
                prefix='forever-storage' if addon=='WFStorage' else 'forever-professions'
                if addon=='WFProfessions' and asset.name=='README.md':
                    raw.decode('utf-8-sig')
                elif asset.name==prefix+'-logo.png':
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid addon branding image.')
                elif asset.name==prefix+'-icon.tga':
                    # Reviewed uncompressed RGBA icon, optional standard footer.
                    dimension=128 if addon=='WFStorage' else 64
                    header=bytes((0,0,2,0,0,0,0,0,0,0,0,0,dimension,0,dimension,0,32,8))
                    size=18+dimension*dimension*4
                    if (raw[:18]!=header or len(raw) not in (size,size+26)
                        or (len(raw)==size+26 and raw[-18:]!=b'TRUEVISION-XFILE.\0')):
                        raise ValueError('Invalid addon branding TGA.')
                else:raise ValueError('Unexpected addon branding file.')
                files.append(asset)
        elif addon=='WFProfessions' and source.is_file() and source.name=='PACKAGE_SHA256.json':
            # This member is itself covered by the externally pinned manifest.
            document=json.loads(source.read_text(encoding='utf-8-sig'))
            if not isinstance(document,dict) or document.get('addon')!=addon or not isinstance(document.get('files'),dict):
                raise ValueError('Invalid Professions package descriptor.')
            files.append(source)
        elif source.is_file() and (source.name=='LICENSE' or source.suffix in ('.lua','.toc','.xml','.md')):
            files.append(source)
        else:raise ValueError('Unexpected addon payload file.')
    return sorted(files,key=lambda p:(p.suffix=='.toc',p.as_posix()))


def install(payload,client,selected,backup_root,*,check_game=False):
    client=Path(client).resolve(strict=True);payload=Path(payload).resolve(strict=True)
    validate_client(client)
    selected=set(selected)
    if not selected or not selected<=set(ADDONS):raise ValueError('Select known Forever addons.')
    if selected&{'WFStorage','WFProfessions'}:selected.add('WFCore')
    if 'WFCore' in selected:check_legacy(client)
    metadata=package_metadata(payload,selected)
    if check_game and game_running():raise ValueError('Close WoW before installing addon updates.')
    jobs=[]
    for addon in sorted(selected):
        for source in package_files(payload,addon):
            target=safe_target(client/'Interface'/'AddOns'/source.relative_to(payload),client)
            jobs.append((source,target,source.read_bytes()))
    jobs.sort(key=lambda job:job[0].suffix=='.toc')  # Publish load lists after all module bytes.
    backup=Path(backup_root).resolve()/datetime.now().strftime('%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True,exist_ok=False)
    before={target:(target.read_bytes() if target.exists() else None) for _,target,_ in jobs}
    for target,raw in before.items():
        if raw is not None:
            saved=backup/target.relative_to(client/'Interface/AddOns');saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(raw)
            if saved.read_bytes()!=raw:raise ValueError('Addon backup verification failed.')
    written=[]
    try:
        for _,target,raw in jobs:
            safe_target(target,client)
            if (target.read_bytes() if target.exists() else None)!=before[target]:raise ValueError('Addon changed while preparing installation.')
            target.parent.mkdir(parents=True,exist_ok=True);written.append(target);target.write_bytes(raw)
            if target.read_bytes()!=raw:raise ValueError('Addon copy verification failed.')
        manifest={'client':str(client),'selected':sorted(selected),'packages':metadata,'files':[{ 'path':str(t.relative_to(client)), 'sha256':hashlib.sha256(raw).hexdigest()} for _,t,raw in jobs]}
        (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    except Exception:
        for target in reversed(written):
            raw=before[target]
            safe_target(target,client)
            if raw is None:
                if target.is_file():target.unlink()
            else:target.write_bytes(raw)
            if (target.read_bytes() if target.exists() else None)!=raw:raise OSError('Addon rollback verification failed.')
        raise
    return manifest
