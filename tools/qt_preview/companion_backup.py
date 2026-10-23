"""Bounded companion-only archives; never traverse linked game-save paths."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
import zipfile

FILES = frozenset(('profiles.json','planning.json','inventory.json','gear_wishlist.json',
    'inventory_filters.json','gear_filters.json','item_search_filters.json','inventory_undo.json',
    'gear_undo.json','display_settings.json','auction_prices.json','qt_fonts.json',
    'playstyle_presets.json','character_links.json','saved_character_connection.json',
    'addon_inventory.json','character_cards.json','close_behavior.json','window_placement.json',
    'addon_connection.json','updates.json'))
LIMIT=5_000_000
TOTAL=50_000_000


def digest(raw):return hashlib.sha256(raw).hexdigest()


def snapshot(directory):
    directory=Path(directory).resolve();result={}
    for name in sorted(FILES):
        path=directory/name
        if path.is_symlink() or path.is_junction():raise ValueError('Linked state files cannot be backed up or restored.')
        if path.exists():
            if not path.is_file() or path.stat().st_size>LIMIT:raise ValueError('Invalid or oversized companion file: '+name)
            result[name]=path.read_bytes()
    if sum(map(len,result.values()))>TOTAL:raise ValueError('Companion data exceeds the backup size limit.')
    return result


def validate_files(files):
    """Use existing readers against isolated staging; no game file is opened."""
    from data import Data
    from character_links import LinkStore
    from observed_inventory import ObservationStore
    from saved_character_connection import validate as connection
    from window_placement import validate as placement
    from close_behavior import validate as closing
    from character_overview import validate_card_preferences
    validators={'saved_character_connection.json':connection,'window_placement.json':placement,
                'close_behavior.json':closing,'character_cards.json':validate_card_preferences}
    with tempfile.TemporaryDirectory(prefix='wf-backup-check-') as tmp:
        folder=Path(tmp)
        for name,raw in files.items():
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('Invalid companion data: '+name)
            if name in validators:validators[name](value)
            if name=='addon_connection.json' and (set(value)!={'client'} or value['client'] is not None and not isinstance(value['client'],str)):
                raise ValueError('Invalid addon-folder preference.')
            if name=='updates.json' and (set(value)!={'automatic'} or type(value['automatic']) is not bool):
                raise ValueError('Invalid update preference.')
            (folder/name).write_bytes(raw)
        data=Data(folder)
        if data.errors():raise ValueError('Backup data is invalid: '+'; '.join(data.errors()))
        links=LinkStore(folder).records['links'];ObservationStore(folder)
        ids={p.id for p in data.saved_profiles}
        if any(e['profile'] not in ids for e in links):raise ValueError('Backup has links to missing character profiles.')
        return [p.name for p in data.saved_profiles], sorted({e['identity']['source'] for e in links})


def inspect(path):
    path=Path(path)
    if path.stat().st_size>TOTAL:raise ValueError('Backup archive is too large.')
    raw=path.read_bytes()
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();names=[e.filename for e in entries]
            if len(names)!=len(set(names)) or set(names)-FILES-{'manifest.json'} or 'manifest.json' not in names:
                raise ValueError('Backup contains duplicate or unsupported paths.')
            if any(e.file_size>LIMIT or e.flag_bits&1 for e in entries) or sum(e.file_size for e in entries)>TOTAL:
                raise ValueError('Backup contents exceed limits or are encrypted.')
            manifest=json.loads(archive.read('manifest.json'))
            if not isinstance(manifest,dict) or manifest.get('format')!='WFCompanionBackup' or manifest.get('version')!=1:
                raise ValueError('Unsupported backup format.')
            datetime.fromisoformat(manifest['created'])
            hashes=manifest['files']
            if not isinstance(hashes,dict) or set(hashes)!=set(names)-{'manifest.json'}:raise ValueError('Backup file list does not match.')
            files={name:archive.read(name) for name in hashes}
            if any(digest(value)!=hashes[name] for name,value in files.items()):raise ValueError('Backup checksum mismatch.')
        characters,sources=validate_files(files)
        return dict(files=files,created=manifest['created'],characters=characters,sources=sources,sha256=digest(raw))
    except (zipfile.BadZipFile,KeyError,TypeError,UnicodeError,RuntimeError,NotImplementedError) as exc:
        raise ValueError('Damaged or unsupported companion backup.') from exc


def create(directory,path):
    directory=Path(directory).resolve();path=Path(path).resolve()
    if path.suffix.lower()!='.zip':raise ValueError('Choose a .zip backup file.')
    files=snapshot(directory);validate_files(files)
    manifest=dict(format='WFCompanionBackup',version=1,created=datetime.now(timezone.utc).isoformat(),
                  files={name:digest(raw) for name,raw in files.items()})
    path.parent.mkdir(parents=True,exist_ok=True)
    handle,temp=tempfile.mkstemp(prefix='.wf-backup-',suffix='.zip',dir=path.parent);os.close(handle)
    temp=Path(temp)
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest))
            for name,raw in files.items():archive.writestr(name,raw)
        inspect(temp)
        if snapshot(directory)!=files:raise ValueError('Companion data changed while backing up; try again.')
        temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
    return path


def replace_files(directory,files):
    for name in sorted(FILES):
        path=directory/name
        if name in files:
            handle,temp=tempfile.mkstemp(prefix='.wf-restore-',dir=directory)
            try:
                with os.fdopen(handle,'wb') as stream:
                    stream.write(files[name]);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            finally:
                if Path(temp).exists():Path(temp).unlink()
        elif path.exists():path.unlink()


def recover_pending(directory):
    directory=Path(directory).resolve();marker=directory/'restore-pending.json'
    if marker.is_symlink() or marker.is_junction():raise ValueError('Linked recovery marker is not supported.')
    if not marker.exists():return
    value=json.loads(marker.read_text())
    name=value.get('recovery') if isinstance(value,dict) else None
    if not isinstance(name,str) or Path(name).name!=name or not name.startswith('before-restore-') or not name.endswith('.zip'):
        raise ValueError('Invalid restore recovery marker; data preserved.')
    snapshot(directory)  # Reject unsafe targets before any writes.
    recovery=inspect(recovery_path(directory,name))
    replace_files(directory,recovery['files']);marker.unlink()


def recovery_path(directory,name):
    folder=directory/'Backups';path=folder/name
    if folder.is_symlink() or folder.is_junction() or path.is_symlink() or path.is_junction():
        raise ValueError('Linked recovery backup paths are not supported.')
    if path.resolve().parent!=folder.resolve() or folder.resolve().parent!=directory.resolve():
        raise ValueError('Recovery backup must stay inside companion data.')
    return path


def restore(directory,path,expected,current):
    directory=Path(directory).resolve();review=inspect(path)
    if review['sha256']!=expected:raise ValueError('Backup changed since preview; preview it again.')
    if snapshot(directory)!=current:raise ValueError('Companion data changed since preview; preview again.')
    if (directory/'restore-pending.json').exists():raise ValueError('A previous restore needs recovery. Reopen the companion first.')
    recovery=recovery_path(directory,'before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.zip')
    create(directory,recovery)
    marker=directory/'restore-pending.json'
    handle,temp=tempfile.mkstemp(prefix='.wf-marker-',dir=directory)
    try:
        with os.fdopen(handle,'w',encoding='utf-8') as stream:
            json.dump(dict(recovery=recovery.name),stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,marker)
    finally:
        if Path(temp).exists():Path(temp).unlink()
    try:
        replace_files(directory,review['files'])
        marker.unlink()
    except OSError:
        recover_pending(directory)
        raise
    return recovery
