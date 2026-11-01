"""Install only selected first-party addon code; preserve game saves and other addons."""
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import csv
import hashlib
import json
import os
import shutil
import subprocess
import re
import stat
import sys
import threading
import uuid

ADDONS=('WFCore','WFStorage','WFProfessions','WFStressProbe','WFDisplayTest')
PINNED_ADDONS={'WFCore','WFStorage','WFProfessions'}

# Foundation APIs only; production installation does not publish pending evidence.
PENDING_NAME='.wf-addon-pending.json'
MAX_PENDING_BYTES=4096
MAX_TRANSACTION_BYTES=1024*1024
MAX_TRANSACTION_FILES=512
MAX_TRANSACTION_FILE_BYTES=16*1024*1024
MAX_TRANSACTION_TOTAL_BYTES=128*1024*1024
_install_locks=set()
_install_locks_guard=threading.Lock()


def client_identity(client):
    """Use directory identity for aliases/case variants, not the supplied spelling."""
    client=validate_client(client)
    _check_windows_link_support(client)
    info=client.stat()
    if any(type(n) is not int or n<=0 for n in (info.st_dev,info.st_ino)):
        raise ValueError('Cannot verify the game folder identity; installation is unavailable.')
    return dict(path=os.path.normcase(str(client)),device=info.st_dev,inode=info.st_ino)


@contextmanager
def installation_lock(client):
    """Cooperative, nonblocking target lock, shared by GUI and CLI installers.

    Global Windows mutexes span login sessions and require no lock file. An
    inaccessible/pre-created mutex fails closed. The OS releases ownership on
    termination; this is exclusion, NOT evidence of a completed installation.
    POSIX fixture/development runs use flock on the existing client directory.
    """
    identity=client_identity(client)
    key=f'{identity["device"]}:{identity["inode"]}'
    busy='Another addon installation is using this game folder. Wait for it to finish before trying again.'
    with _install_locks_guard:
        if key in _install_locks:raise ValueError(busy)
        _install_locks.add(key)  # Also prevent same-thread recursive Windows mutex ownership.
    try:
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR)
            kernel.CreateMutexW.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
            kernel.WaitForSingleObject.restype=wintypes.DWORD
            kernel.ReleaseMutex.argtypes=(wintypes.HANDLE,);kernel.ReleaseMutex.restype=wintypes.BOOL
            kernel.CloseHandle.argtypes=(wintypes.HANDLE,);kernel.CloseHandle.restype=wintypes.BOOL
            name='Global\\WFCompanion.AddonInstall.'+hashlib.sha256(key.encode('ascii')).hexdigest()
            handle=kernel.CreateMutexW(None,False,name)
            if not handle:raise OSError('Cannot acquire the addon installation lock; check Windows permissions.')
            owned=False
            try:
                result=kernel.WaitForSingleObject(handle,0)
                if result==0x102:raise ValueError(busy)
                if result not in (0,0x80):raise OSError('Cannot acquire the addon installation lock.')
                owned=True
                # WAIT_ABANDONED grants ownership, but does not prove consistency.
                # Milestone 2 must check pending state here before any mutation.
                yield identity
            finally:
                try:
                    if owned and not kernel.ReleaseMutex(handle):raise OSError('Cannot release the addon installation lock.')
                finally:kernel.CloseHandle(handle)
        else:
            import fcntl
            descriptor=os.open(client,os.O_RDONLY)
            try:
                try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError(busy) from None
                yield identity
            finally:os.close(descriptor)
    finally:
        with _install_locks_guard:_install_locks.remove(key)


def _fields(value,names):
    if not isinstance(value,dict) or set(value)!=set(names):raise ValueError('Unexpected transaction record fields.')


def _relative_member(value):
    # Canonical ASCII paths only: no ADS, device names, 8.3 aliases, separator
    # aliases, trailing dots/spaces or Windows case-equivalent duplicate names.
    if not isinstance(value,str) or not 1<=len(value)<=240:raise ValueError('Unsafe transaction path.')
    parts=value.split('/')
    for part in parts:
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+',part) or part in ('.','..') or part.endswith('.')
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?',part,re.I)):
            raise ValueError('Unsafe transaction path.')
    return parts


def _size_hash(value):
    _fields(value,('size','sha256'))
    if type(value['size']) is not int or not 0<=value['size']<=MAX_TRANSACTION_FILE_BYTES:
        raise ValueError('Invalid transaction file size.')
    if not isinstance(value['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['sha256']):
        raise ValueError('Invalid transaction SHA-256.')


def _transaction_directory(directory):
    path=Path(os.path.abspath(directory))
    safe_target(path,Path(path.anchor))  # Do not erase links by resolving first.
    if not path.is_dir():raise ValueError('Recovery directory is unavailable.')
    return path.resolve(strict=True)


def _transaction_json(raw,limit):
    """Shared bounded, duplicate-rejecting decoder for untrusted evidence."""
    if not isinstance(raw,bytes) or not 1<=len(raw)<=limit:
        raise ValueError('Invalid or oversized transaction record.')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate transaction JSON field.')
            result[key]=value
        return result
    def invalid_constant(value):raise ValueError('Invalid JSON constant.')
    try:return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid_constant)
    except (UnicodeError,ValueError,RecursionError) as exc:raise ValueError('Malformed transaction record.') from exc


def validate_transaction(raw,client,recovery_directory):
    """Validate untrusted bytes without mutation; caller supplies both trusted roots.

    Schema 1 is an immutable intent record, not a progress counter. Paths are
    relative to Interface/AddOns or the caller's existing backup directory.
    File contents/receipt hashes must still be verified before future recovery;
    this function is not authority to overwrite files or a pending-state writer.
    Revalidate under installation_lock immediately before future mutation.
    """
    record=_transaction_json(raw,MAX_TRANSACTION_BYTES)
    _fields(record,('schema','id','client','destination','selected','expanded','packages','files','receipt'))
    if type(record['schema']) is not int or record['schema']!=1:raise ValueError('Unsupported transaction schema.')
    identifier=record['id']
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier) or uuid.UUID(hex=identifier).version!=4:
        raise ValueError('Invalid transaction ID; expected UUID4 hex.')
    identity=client_identity(client);client=validate_client(client)
    _fields(record['client'],('path','device','inode'))
    if (any(type(record['client'][k]) is not int for k in ('device','inode')) or record['client']!=identity
        or record['destination']!='Interface/AddOns'):
        raise ValueError('Transaction belongs to a different game folder or destination.')
    recovery=_transaction_directory(recovery_directory)
    if recovery.is_relative_to(client) or client.is_relative_to(recovery):
        raise ValueError('Recovery directory must be separate from the game folder.')
    for field in ('selected','expanded'):
        values=record[field]
        if (not isinstance(values,list) or not values or len(values)>len(ADDONS)
            or any(not isinstance(v,str) or v not in ADDONS for v in values) or len(set(values))!=len(values)):
            raise ValueError('Invalid transaction addon selection.')
    expanded=set(record['selected'])
    if expanded&{'WFStorage','WFProfessions'}:expanded.add('WFCore')
    if set(record['expanded'])!=expanded:raise ValueError('Invalid transaction Core dependencies.')
    packages=record['packages']
    _fields(packages,expanded&PINNED_ADDONS)
    for package in packages.values():
        _fields(package,('source_commit','archive_sha256'))
        for field,length in (('source_commit',40),('archive_sha256',64)):
            if not isinstance(package[field],str) or not re.fullmatch('[a-f0-9]{'+str(length)+'}',package[field]):
                raise ValueError('Invalid transaction package identity.')
    files=record['files']
    if not isinstance(files,list) or not 1<=len(files)<=MAX_TRANSACTION_FILES:raise ValueError('Invalid transaction file count.')
    seen=set();tocs=set();toc_started=False;total=0
    for index,item in enumerate(files):
        _fields(item,('path','existed','original','replacement','stage','backup'))
        parts=_relative_member(item['path']);relative=item['path']
        if relative.lower() in seen:raise ValueError('Duplicate Windows transaction path.')
        seen.add(relative.lower())
        if parts[0] not in expanded or len(parts) not in (2,3):raise ValueError('Transaction path is outside selected addons.')
        addon=parts[0];name=parts[-1]
        if len(parts)==3:
            prefix={'WFCore':'wfcompanion','WFStorage':'forever-storage','WFProfessions':'forever-professions'}.get(addon)
            allowed={prefix+'-icon.tga'} if prefix else set()
            if prefix and addon!='WFCore':allowed.add(prefix+'-logo.png')
            if addon=='WFProfessions':allowed.add('README.md')
            if parts[1]!='branding' or name not in allowed:raise ValueError('Unsupported transaction asset.')
        elif not (name=='LICENSE' or name.endswith(('.lua','.xml','.md')) or name==addon+'.toc'
                  or (addon=='WFProfessions' and name=='PACKAGE_SHA256.json')):
            raise ValueError('Unsupported transaction addon file.')
        if name.endswith('.toc'):toc_started=True;tocs.add(addon)
        elif toc_started:raise ValueError('Transaction must publish TOCs last.')
        if type(item['existed']) is not bool:raise ValueError('Invalid original-file presence.')
        if item['existed']:
            _size_hash(item['original'])
            if item['backup']!=relative:raise ValueError('Invalid recovery backup reference.')
            safe_target(recovery/relative,recovery,for_write=True)
            total+=item['original']['size']
        elif item['original'] is not None or item['backup'] is not None:
            raise ValueError('Absent original must not reference backup bytes.')
        _size_hash(item['replacement']);total+=item['replacement']['size']
        expected='/'.join(parts[:-1]+[f'.wf-{identifier}-{index}.stage'])
        if item['stage']!=expected:raise ValueError('Invalid transaction-owned staging name.')
        safe_target(client/'Interface/AddOns'/relative,client,for_write=True)
        safe_target(client/'Interface/AddOns'/expected,client,for_write=True)
    if tocs!=expanded:raise ValueError('Transaction must include each selected addon TOC.')
    receipt=record['receipt'];_fields(receipt,('path','size','sha256'))
    if receipt['path']!='manifest.json':raise ValueError('Invalid completed receipt reference.')
    _size_hash({k:receipt[k] for k in ('size','sha256')})
    if total+receipt['size']>MAX_TRANSACTION_TOTAL_BYTES:raise ValueError('Transaction exceeds aggregate size limit.')
    safe_target(recovery/'manifest.json',recovery,for_write=True)
    return record


def read_transaction(client,recovery_directory):
    """Bounded reader for a fixed filename; never follow a metadata-supplied root."""
    recovery=_transaction_directory(recovery_directory)
    path=safe_target(recovery/'transaction.json',recovery,for_write=True)
    with path.open('rb') as stream:raw=stream.read(MAX_TRANSACTION_BYTES+1)
    return validate_transaction(raw,client,recovery)


def _byte_description(raw):
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def _file_stamp(info):
    if any(type(n) is not int or n<=0 for n in (info.st_dev,info.st_ino)):
        raise ValueError('Cannot verify preparation file identity.')
    # Python 3.12 Windows stat/fstat can expose different ctime semantics.
    # Compare identity, size, mtime and links there; bytes are compared separately.
    change_time=None if os.name=='nt' else info.st_ctime_ns
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,change_time,info.st_nlink)


def _read_preparation_file(path,root,*,missing=False,max_bytes=MAX_TRANSACTION_FILE_BYTES):
    """Bounded read tied to an unchanged, independent regular file object."""
    safe_target(path,root,for_write=True)
    try:before=path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if missing:return None,None
        raise
    stamp=_file_stamp(before)
    limit=min(max_bytes,MAX_TRANSACTION_FILE_BYTES)
    if before.st_size>limit:raise ValueError('Preparation file exceeds size limit.')
    with path.open('rb') as stream:
        if _file_stamp(os.fstat(stream.fileno()))!=stamp:raise ValueError('File changed during preparation.')
        raw=stream.read(limit+1)
        if _file_stamp(os.fstat(stream.fileno()))!=stamp:raise ValueError('File changed during preparation.')
    safe_target(path,root,for_write=True)
    if len(raw)!=before.st_size or _file_stamp(path.stat(follow_symlinks=False))!=stamp:
        raise ValueError('File changed during preparation.')
    return raw,stamp


class TransactionPreparationError(OSError):
    def __init__(self,error,cleanup_failures):
        self.preparation_error=error
        self.cleanup_failures=tuple(cleanup_failures)
        # Preserve exceptions/paths for diagnostics, not private OS messages in UI text.
        message='Transaction preparation failed; no addon destination files were replaced.'
        if cleanup_failures:message+=' Some temporary artifacts were preserved; review cleanup failures before retrying.'
        super().__init__(message)


def _preparation_mkdir(path,root,directories):
    safe_target(path,root)
    if path.is_dir():return
    if path.parent!=root:_preparation_mkdir(path.parent,root,directories)
    safe_target(path,root)
    path.mkdir()  # Exclusive; a concurrent creator is not our directory.
    directories.append((path,root,None))
    info=path.stat(follow_symlinks=False)
    directories[-1]=(path,root,_file_stamp(info)[:2])


def _write_preparation_artifact(path,root,raw,artifacts,directories):
    _transaction_directory(root)
    _preparation_mkdir(path.parent,root,directories)
    safe_target(path,root,for_write=True)
    with path.open('xb',buffering=0) as stream:
        entry=dict(path=path,root=root,identity=None,expected=None,verified_stamp=None)
        artifacts.append(entry)  # Even a subsequent fstat/write failure needs reporting.
        info=os.fstat(stream.fileno());entry['identity']=_file_stamp(info)[:2]
        # On an exceptional write the number of bytes written is unknown: retain it.
        count=stream.write(raw)
        if type(count) is not int or not 0<=count<=len(raw):raise OSError('Invalid artifact write result.')
        entry['expected']=raw[:count]
        if count!=len(raw):raise OSError('Incomplete preparation artifact write.')
        stream.flush()
        os.fsync(stream.fileno())  # A failed sync is a preparation failure, never ignored.
    observed,stamp=_read_preparation_file(path,root)
    if stamp[:2]!=entry['identity'] or _byte_description(observed)!=_byte_description(raw):
        raise ValueError('Preparation artifact verification failed.')
    entry['verified_stamp']=stamp


def _cleanup_preparation(artifacts,directories):
    """Best effort, all entries attempted; never recurse or delete ambiguous bytes."""
    failures=[]
    for entry in reversed(artifacts):
        path=entry['path'];root=entry['root']
        try:
            _transaction_directory(root)
            raw,stamp=_read_preparation_file(path,root,missing=True)
            if raw is None:continue
            if entry['expected'] is None or stamp[:2]!=entry['identity'] or raw!=entry['expected']:
                raise ValueError('Ambiguous or externally changed artifact preserved.')
            if entry['verified_stamp'] is not None and stamp!=entry['verified_stamp']:
                raise ValueError('Artifact metadata changed after verification; preserved.')
            safe_target(path,root,for_write=True)
            if _file_stamp(path.stat(follow_symlinks=False))!=stamp:
                raise ValueError('Artifact changed before cleanup; preserved.')
            path.unlink()
        except Exception as exc:failures.append((path,exc))
    for path,root,identity in reversed(directories):
        try:
            _transaction_directory(root);safe_target(path,root)
            if not path.exists():continue
            info=path.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=identity:
                raise ValueError('Changed preparation directory preserved.')
            path.rmdir()  # Nonempty directories (including external files) are preserved.
        except Exception as exc:failures.append((path,exc))
    return failures


def _recovery_root_identity(root):
    root=_transaction_directory(root)
    _check_windows_link_support(root)
    info=root.stat()
    device,inode=_file_stamp(info)[:2]
    return dict(path=os.path.normcase(str(root)),device=device,inode=inode)


def _validate_pending(raw,client,backup_root):
    marker=_transaction_json(raw,MAX_PENDING_BYTES)
    _fields(marker,('schema','id','client','backup_root','transaction'))
    if type(marker['schema']) is not int or marker['schema']!=1:raise ValueError('Unsupported pending schema.')
    identifier=marker['id']
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier) or uuid.UUID(hex=identifier).version!=4:
        raise ValueError('Invalid pending transaction ID.')
    for key,expected in (('client',client_identity(client)),('backup_root',_recovery_root_identity(backup_root))):
        _fields(marker[key],('path','device','inode'))
        if any(type(marker[key][k]) is not int for k in ('device','inode')) or marker[key]!=expected:
            raise ValueError('Pending evidence belongs to a different directory.')
    _size_hash(marker['transaction'])
    if not 1<=marker['transaction']['size']<=MAX_TRANSACTION_BYTES:raise ValueError('Invalid pending transaction size.')
    return marker


def _inspect_pending_locked(client,backup_root,*,locked_identity=None):
    """Read-only implementation; caller must hold the shared client lock."""
    try:
        client=validate_client(client)
        if locked_identity is not None and client_identity(client)!=locked_identity:
            raise ValueError('Game folder no longer matches the acquired transaction lock.')
        # Even an incomplete publication stage blocks a new foundation transaction.
        # Do not read or delete its contents, or enumerate unrelated addon files.
        # scandir propagates access errors; glob may silently suppress them.
        with os.scandir(client) as entries:
            if any(entry.name.casefold().startswith('.wf-addon-pending-') and entry.name.casefold().endswith('.stage') for entry in entries):
                return dict(state='ambiguous',reason='Unfinished pending publication; preserve recovery evidence.')
        raw,marker_stamp=_read_preparation_file(client/PENDING_NAME,client,missing=True,max_bytes=MAX_PENDING_BYTES)
        if raw is None:return dict(state='none')
        backup_root=_transaction_directory(backup_root)
        marker=_validate_pending(raw,client,backup_root)
        if locked_identity is not None and marker['client']!=locked_identity:
            raise ValueError('Pending evidence does not belong to the locked game folder.')
        recovery=_transaction_directory(backup_root/('prepare-'+marker['id']))
        record_raw,record_stamp=_read_preparation_file(recovery/'transaction.json',backup_root,max_bytes=MAX_TRANSACTION_BYTES)
        if _byte_description(record_raw)!=marker['transaction']:raise ValueError('Transaction digest mismatch.')
        record=validate_transaction(record_raw,client,recovery)
        if record['id']!=marker['id']:raise ValueError('Pending transaction ID mismatch.')
        checked=[(client/PENDING_NAME,client,raw,marker_stamp),(recovery/'transaction.json',backup_root,record_raw,record_stamp)]
        destinations=[];conflicts=[]
        for item in record['files']:
            target=client/'Interface/AddOns'/item['path']
            content,stamp=_read_preparation_file(target,client,missing=True)
            description=_byte_description(content) if content is not None else None
            if item['existed'] and description==item['original']:state='original'
            elif not item['existed'] and content is None:state='original_absence'
            elif description==item['replacement']:state='replacement'
            else:state='unexpected';conflicts.append(item['path'])
            destinations.append(dict(path=item['path'],state=state,content=content,stamp=stamp))
            checked.append((target,client,content,stamp))
            stage=client/'Interface/AddOns'/item['stage']
            stage_content,stage_stamp=_read_preparation_file(stage,client,missing=True)
            if stage_content is not None and _byte_description(stage_content)!=item['replacement']:
                raise ValueError('Recovery stage mismatch.')
            # Missing stages alone do not prove replacement. Destination state and
            # every original backup are independently verified below.
            destinations[-1]['stage']=(stage,stage_content,stage_stamp)
            checked.append((stage,client,stage_content,stage_stamp))
            references=[]
            if item['existed']:references.append((recovery/item['backup'],backup_root,item['original']))
            for path,root,expected in references:
                content,stamp=_read_preparation_file(path,root)
                if _byte_description(content)!=expected:raise ValueError('Recovery artifact mismatch.')
                destinations[-1]['backup']=(path,content,stamp)
                checked.append((path,root,content,stamp))
        receipt,stamp=_read_preparation_file(recovery/'receipt.pending',backup_root)
        if _byte_description(receipt)!={k:record['receipt'][k] for k in ('size','sha256')}:
            raise ValueError('Expected receipt mismatch.')
        checked.append((recovery/'receipt.pending',backup_root,receipt,stamp))
        for path,root,content,stamp in checked:
            if _read_preparation_file(path,root,missing=content is None)!=(content,stamp):raise ValueError('Evidence changed during inspection.')
        _validate_pending(raw,client,backup_root)
        if conflicts:
            return dict(state='ambiguous',reason='Unexpected addon contents; preserve files and recovery evidence.',affected=conflicts)
        # Private snapshots are attempt-local guards, never persisted authority.
        return dict(state='valid',record=record,recovery=recovery,destinations=destinations,
                    _bindings=[checked[0],checked[1],checked[-1]])
    except Exception as exc:
        # No untrusted paths or private OS messages in user-facing diagnostics.
        return dict(state='invalid',reason='Pending evidence is invalid or incomplete; preserve all evidence.',error=exc)


@contextmanager
def _transaction_client_lock(client):
    """Pin the destination before locking; caller aliases are only change guards."""
    requested=Path(os.path.abspath(client))
    canonical=validate_client(requested)
    retained=client_identity(canonical)
    with installation_lock(canonical) as acquired:
        if (acquired!=retained or client_identity(canonical)!=retained
            or client_identity(requested)!=retained):
            raise ValueError('Game folder changed while acquiring transaction lock; recovery was not started.')
        # Never yield the mutable alias for inspection or destination construction.
        yield canonical,retained


def inspect_pending_transaction(client,backup_root):
    """Read-only inspection under the same lock used by every installer entry point.

    backup_root is a trusted caller input, never a path obtained from the marker.
    Production uses its deterministic root wrapper and the same locked inspector;
    this explicit-root entry point remains available for isolated fixtures.
    """
    with _transaction_client_lock(client) as (canonical,identity):
        return _inspect_pending_locked(canonical,backup_root,locked_identity=identity)


class InstallationGuardError(ValueError):
    """Stable, public-safe preflight failure; private diagnostics stay on the cause."""
    def __init__(self,code):
        self.code=code
        super().__init__({
            'recovery_pending':'Addon recovery is pending for this game folder. Resolve it before installing; preserve recovery evidence.',
            'recovery_invalid':'Addon recovery evidence is invalid or incomplete. Installation is blocked; preserve recovery evidence.',
            'recovery_ambiguous':'Addon recovery state is uncertain. Installation is blocked; preserve files and recovery evidence.',
            'recovery_location_unavailable':'The trusted addon recovery location is inaccessible or unsafe. Check folder access and links; installation was not started.',
            'client_identity_changed':'The game folder changed during installation preflight. Installation was not started.',
        }[code])


def _production_recovery_location(client,identity):
    """Derive and inspect, never create. Caller holds the pinned client lock."""
    if client_identity(client)!=identity:raise InstallationGuardError('client_identity_changed')
    key=f"{identity['device']}:{identity['inode']}".encode('ascii')
    root=client.parent/'.wfcompanion-addon-recovery'/hashlib.sha256(key).hexdigest()
    try:
        # Inspect lexical paths before resolving: a linked namespace/root must not
        # be silently accepted as an alternative recovery location.
        safe_target(root,Path(root.anchor))
        _check_windows_link_support(client.parent)
        found=None
        for directory in (root.parent,root):
            try:info=directory.stat(follow_symlinks=False)
            except FileNotFoundError:
                # Also establish that the nearest existing parent is readable.
                with os.scandir(directory.parent):pass
                break
            if not stat.S_ISDIR(info.st_mode):raise ValueError('Recovery location is not a directory.')
            _transaction_directory(directory)
            with os.scandir(directory):pass  # Permission failures must propagate.
            if directory==root:found=_recovery_root_identity(root)
        return root,found
    except Exception as exc:
        raise InstallationGuardError('recovery_location_unavailable') from exc


def production_recovery_root(client):
    """Read-only deterministic lookup, independent of Companion state/backup paths."""
    with _transaction_client_lock(client) as (canonical,identity):
        return _production_recovery_location(canonical,identity)[0]


def _inspect_production_pending_locked(client,identity):
    root,root_identity=_production_recovery_location(client,identity)
    result=_inspect_pending_locked(client,root,locked_identity=identity)
    # Catch replacement/removal during inspection, even when no marker exists.
    if _production_recovery_location(client,identity)!=(root,root_identity):
        raise InstallationGuardError('recovery_location_unavailable')
    result['root_state']=('existing' if root_identity is not None else
                          'absent_unproven' if result['state']=='none' else 'missing_with_pending_evidence')
    return result


def inspect_production_pending(client):
    """Read-only production lookup; does not resolve, repair or retire evidence."""
    with _transaction_client_lock(client) as (canonical,identity):
        return _inspect_production_pending_locked(canonical,identity)


def _check_recovery_inputs(status,item,observed,client,backup_root):
    """Fresh checks immediately before mutation; caller owns the client lock."""
    for path,root,content,stamp in status['_bindings']:
        if _read_preparation_file(path,root)!=(content,stamp):
            raise ValueError('Pending binding changed during recovery.')
    marker=status['_bindings'][0][2]
    _validate_pending(marker,client,backup_root)
    stage,content,stamp=observed['stage']
    if _read_preparation_file(stage,client,missing=True)!=(content,stamp):
        raise ValueError('Staging evidence changed during recovery.')
    if item['existed']:
        path,content,stamp=observed['backup']
        if _read_preparation_file(path,backup_root)!=(content,stamp):
            raise ValueError('Original backup changed during recovery.')
    target=client/'Interface/AddOns'/item['path']
    if _read_preparation_file(target,client,missing=True)!=(observed['content'],observed['stamp']):
        raise ValueError('Destination changed during recovery; preserved.')


def _recover_pending_locked(client,backup_root,identity):
    status=_inspect_pending_locked(client,backup_root,locked_identity=identity)
    if status['state']=='none':return dict(state='none',failures=[])
    if status['state']!='valid':
        return dict(state='blocked',reason=status['reason'],inspection=status,failures=[])
    failures=[]
    for item,observed in reversed(list(zip(status['record']['files'],status['destinations']))):
        artifacts=[];directories=[]
        try:
            _check_recovery_inputs(status,item,observed,client,backup_root)
            target=client/'Interface/AddOns'/item['path']
            if observed['state']=='replacement':
                if item['existed']:
                    # Never consume the only original copy. Exclusive sibling
                    # staging permits a later same-filesystem atomic replacement.
                    stage=target.parent/f'.wf-restore-{uuid.uuid4().hex}.stage'
                    original=observed['backup'][1]
                    _write_preparation_artifact(stage,client,original,artifacts,directories)
                    entry=artifacts[-1]
                    _check_recovery_inputs(status,item,observed,client,backup_root)
                    if _read_preparation_file(stage,client)!=(original,entry['verified_stamp']):
                        raise ValueError('Restoration copy changed; preserved.')
                    safe_target(target,client,for_write=True)
                    if _file_stamp(target.stat(follow_symlinks=False))!=observed['stamp']:
                        raise ValueError('Destination identity changed before replacement; preserved.')
                    os.replace(stage,target)
                else:
                    # The fresh content/identity check above proved this is the
                    # transaction's replacement, not an unrelated new file.
                    target.unlink()
            restored,_=_read_preparation_file(target,client,missing=True)
            if (item['existed'] and (restored is None or _byte_description(restored)!=item['original'])) or (not item['existed'] and restored is not None):
                raise ValueError('Original destination state could not be verified.')
        except Exception as exc:
            failures.append(dict(path=item['path'],reason='File recovery failed; preserve evidence before retrying.',error=exc))
        finally:
            # Only copies owned by this attempt; never backups, original stages,
            # marker or transaction record. BaseException still propagates.
            try:cleanup=_cleanup_preparation(artifacts,directories)
            except Exception as exc:cleanup=[(None,exc)]
            for _,exc in cleanup:
                failures.append(dict(path=item['path'],reason='Restoration temporary file cleanup failed; preserve it.',error=exc))
    final=_inspect_pending_locked(client,backup_root,locked_identity=identity)
    if final['state']!='valid' or final.get('_bindings')!=status['_bindings'] or any(
            entry['state'] not in ('original','original_absence') for entry in final.get('destinations',[])):
        failures.append(dict(path=None,reason='Complete original state and evidence could not be verified.',inspection=final))
    if failures:
        return dict(state='incomplete',reason='Recovery incomplete; some files may remain changed. Preserve all recovery evidence.',failures=failures)
    return dict(state='rollback_complete',reason='Original file state verified; recovery evidence retained.',failures=[])


def recover_pending_transaction(client,backup_root):
    """Explicit isolated rollback API; no production caller or evidence retirement.

    Public reasons are fixed text and paths are validated relative members.
    Exception objects/inspection details are private diagnostics, not UI strings.
    Process interruptions propagate and leave published evidence available.
    """
    with _transaction_client_lock(client) as (canonical,identity):
        try:
            return _recover_pending_locked(canonical,_transaction_directory(backup_root),identity)
        except Exception as exc:
            return dict(state='incomplete',reason='Recovery could not complete; preserve all recovery evidence.',
                        failures=[dict(path=None,reason='Recovery operation failed.',error=exc)])


def _verify_terminal_destinations(status,outcome):
    """Explicit outcome, independent of original/replacement classification priority."""
    for item,observed in zip(status['record']['files'],status['destinations']):
        expected=item['replacement'] if outcome=='installation' else item['original']
        raw=observed['content']
        if (None if raw is None else _byte_description(raw))!=expected:
            raise ValueError('Managed destinations do not match the requested terminal outcome.')


def _completion_receipt(status,client):
    raw=status['_bindings'][-1][2];record=status['record']
    receipt=_transaction_json(raw,MAX_TRANSACTION_FILE_BYTES)
    _fields(receipt,('client','selected','packages','files'))
    expected=[dict(path=str(Path('Interface/AddOns')/item['path']),sha256=item['replacement']['sha256'])
              for item in record['files']]
    if (not isinstance(receipt['client'],str) or os.path.normcase(receipt['client'])!=record['client']['path']
        or receipt['selected']!=record['expanded']
        or receipt['files']!=expected):
        raise ValueError('Expected receipt does not describe this transaction.')
    _fields(receipt['packages'],record['packages'])
    for addon,pins in record['packages'].items():
        info=receipt['packages'][addon]
        if not isinstance(info,dict) or any(info.get(k)!=v for k,v in pins.items()):
            raise ValueError('Expected receipt package identity mismatch.')
        members={item['path'].split('/',1)[1]:item['replacement']['sha256']
                 for item in record['files'] if item['path'].startswith(addon+'/')}
        if info.get('files')!=members:raise ValueError('Expected receipt membership mismatch.')
    return raw


def _publish_completion_receipt(status,client,backup_root):
    """Non-overwriting publication; uncertain stages/receipts remain for inspection."""
    raw=_completion_receipt(status,client);recovery=status['recovery']
    receipt=recovery/status['record']['receipt']['path']
    stage=recovery/f'.wf-receipt-{status["record"]["id"]}.stage'
    current,stamp=_read_preparation_file(receipt,backup_root,missing=True)
    if current is not None and current!=raw:raise ValueError('Conflicting completion receipt; preserve it.')
    staged,stage_stamp=_read_preparation_file(stage,backup_root,missing=True)
    if staged is not None and staged!=raw:raise ValueError('Incomplete or conflicting receipt stage; preserve it.')
    if current is None:
        if staged is None:
            artifacts=[]
            _write_preparation_artifact(stage,backup_root,raw,artifacts,[])
            stage_stamp=artifacts[-1]['verified_stamp']
        if _read_preparation_file(stage,backup_root)!=(raw,stage_stamp):
            raise ValueError('Receipt stage changed before publication.')
        _publish_pending_file(stage,receipt,backup_root)  # Windows no-overwrite rename.
        current,stamp=_read_preparation_file(receipt,backup_root)
        if current!=raw:raise ValueError('Published receipt could not be verified.')
    return receipt,raw,stamp


def _retirement_guard(client,identity,backup_root,root_identity):
    if client_identity(client)!=identity or _recovery_root_identity(backup_root)!=root_identity:
        raise ValueError('Retirement directory identity changed; preserve remaining evidence.')
    if _read_preparation_file(client/PENDING_NAME,client,missing=True,max_bytes=MAX_PENDING_BYTES)!=(None,None):
        raise ValueError('Pending marker is present; preserve remaining evidence.')


def _retirement_artifacts(status,client,backup_root):
    """Capture cleanup identities while pending evidence is still intact."""
    recovery=status['recovery'];safe_target(recovery,backup_root)
    entries=[];directories={recovery:_file_stamp(recovery.stat(follow_symlinks=False))[:2]}
    for observed in status['destinations']:
        path,raw,stamp=observed['stage']
        if raw is not None:entries.append((path,client,raw,stamp))
        if 'backup' in observed:
            path,raw,stamp=observed['backup'];entries.append((path,backup_root,raw,stamp))
    # A matching receipt stage left by an interrupted attempt is also bounded.
    receipt_stage=recovery/f'.wf-receipt-{status["record"]["id"]}.stage'
    raw,stamp=_read_preparation_file(receipt_stage,backup_root,missing=True)
    if raw is not None:
        if raw!=status['_bindings'][-1][2]:raise ValueError('Changed receipt stage preserved.')
        entries.append((receipt_stage,backup_root,raw,stamp))
    # Only backup directories named by the transaction, never game directories.
    for path,root,_,_ in entries:
        if root!=backup_root:continue
        directory=path.parent
        while directory!=backup_root:
            safe_target(directory,backup_root)
            directories[directory]=_file_stamp(directory.stat(follow_symlinks=False))[:2]
            directory=directory.parent
    return entries,directories


def _retire_verified_artifacts(status,client,identity,backup_root,plan,keep_receipt):
    """No recursive deletion or discovery: only exact inspected evidence members."""
    marker=_validate_pending(status['_bindings'][0][2],client,backup_root)
    root_identity=marker['backup_root'];recovery=status['recovery']
    entries,directories=plan
    failures=[]
    def remove(entry):
        path,root,raw,stamp=entry
        try:
            _retirement_guard(client,identity,backup_root,root_identity)
            artifact=dict(path=path,root=root,identity=stamp[:2],expected=raw,verified_stamp=stamp)
            errors=_cleanup_preparation([artifact],[])
            failures.extend(errors)
        except Exception as exc:failures.append((path,exc))
    for entry in entries:remove(entry)
    # Retain the record and receipt.pending if any earlier cleanup is uncertain.
    if not failures:
        for entry in reversed(status['_bindings'][1:]):
            remove(entry)
            if failures:break
    if not failures:
        for directory,stamp in sorted(directories.items(),key=lambda entry:len(entry[0].parts),reverse=True):
            if directory==recovery and keep_receipt:continue  # Keep verified manifest.json.
            try:
                _retirement_guard(client,identity,backup_root,root_identity)
                failures.extend(_cleanup_preparation([],[(directory,backup_root,stamp)]))
            except Exception as exc:failures.append((directory,exc))
    return failures


def _finalize_transaction(client,backup_root,outcome):
    with _transaction_client_lock(client) as (canonical,identity):
        return _finalize_transaction_locked(canonical,backup_root,identity,outcome)


def _finalize_transaction_locked(canonical,backup_root,identity,outcome,*,retained=None,observer=None):
    """Caller retains the canonical client lock through verification and retirement."""
    retired=False;failures=[]
    try:
        backup_root=_transaction_directory(backup_root)
        status=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
        if status['state']=='none':
            return dict(state='no_pending',retired=False,failures=[],reason='No pending transaction; no outcome inferred or residual evidence removed.')
        if status['state']!='valid':
            return dict(state='blocked',retired=False,failures=[],inspection=status,reason='Completion blocked; preserve all recovery evidence.')
        _verify_terminal_destinations(status,outcome)
        receipt=None
        if outcome=='installation':
            if retained is not None:retained.publish_receipt()
            receipt=_publish_completion_receipt(status,canonical,backup_root)
        else:
            # A prior publication attempt may have left a receipt. Never
            # overwrite/delete it or silently retire a conflicting one.
            expected=_completion_receipt(status,canonical)
            path=status['recovery']/status['record']['receipt']['path']
            raw,stamp=_read_preparation_file(path,backup_root,missing=True)
            if raw is not None:
                if raw!=expected:raise ValueError('Conflicting completion receipt; preserve it.')
                receipt=path,raw,stamp
        # Finish read-only cleanup planning before the last full inspection.
        # Planning can take time; its earlier destination snapshots are not
        # authority to retire evidence without revalidation afterward.
        plan=_retirement_artifacts(status,canonical,backup_root)
        if retained is not None:retained.verify(require_receipt=True)
        # Optional service evidence survives retirement. Publish before the final
        # full revalidation, so status I/O cannot make that last check stale.
        if observer is not None:observer.terminal(status,outcome)
        fresh=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
        if fresh!=status:raise ValueError('Transaction changed during completion; preserve evidence.')
        _verify_terminal_destinations(fresh,outcome)
        if receipt and _read_preparation_file(receipt[0],backup_root)!=receipt[1:]:
            raise ValueError('Completion receipt changed; preserve evidence.')
        marker,root,raw,stamp=status['_bindings'][0]
        if _read_preparation_file(marker,root,max_bytes=MAX_PENDING_BYTES)!=(raw,stamp):
            raise ValueError('Pending marker changed before retirement.')
        _validate_pending(raw,canonical,backup_root)
        if observer is not None:observer.check()
        marker.unlink()
        _retirement_guard(canonical,identity,backup_root,_validate_pending(raw,canonical,backup_root)['backup_root'])
        retired=True  # Only after verified absence; no finally-based evidence cleanup.
        failures=_retire_verified_artifacts(status,canonical,identity,backup_root,plan,receipt is not None)
        _retirement_guard(canonical,identity,backup_root,_validate_pending(raw,canonical,backup_root)['backup_root'])
        # Recheck terminal bytes even if an unrelated actor changed files during cleanup.
        for item in status['record']['files']:
            content,_=_read_preparation_file(canonical/'Interface/AddOns'/item['path'],canonical,missing=True)
            expected=item['replacement'] if outcome=='installation' else item['original']
            if (None if content is None else _byte_description(content))!=expected:
                raise ValueError('Terminal destination changed during retirement.')
        if receipt and _read_preparation_file(receipt[0],backup_root)!=receipt[1:]:
            raise ValueError('Completion receipt changed during retirement.')
        if retained is not None:retained.verify(require_receipt=True)
        return dict(state=outcome+'_complete',retired=True,failures=failures,
                    reason='Terminal state verified and pending marker retired.' if not failures else
                           'Terminal state verified and pending marker retired; residual evidence requires review.')
    except Exception as exc:
        return dict(state='incomplete',retired=retired,failures=failures+[(None,exc)],
                    reason='Completion could not be fully verified; preserve remaining evidence.')


def complete_pending_installation(client,backup_root,*,retained_backup_root=None):
    """Explicit isolated install completion; no production callers."""
    if retained_backup_root is not None:
        with _transaction_client_lock(client) as (canonical,identity):
            try:
                status=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
                if status['state']!='valid':
                    return dict(state='blocked',retired=False,failures=[],inspection=status,
                                reason='Completion requires valid pending evidence.')
                retained=RetainedUserBackup(status['record'],_completion_receipt(status,canonical),
                                          canonical,backup_root,retained_backup_root)
                retained.verify()
                return _finalize_transaction_locked(canonical,backup_root,identity,'installation',retained=retained)
            except Exception as exc:
                return dict(state='incomplete',retired=False,failures=[(None,exc)],
                            reason='Retained user backup could not be verified; preserve recovery evidence.')
    return _finalize_transaction(client,backup_root,'installation')


def complete_pending_rollback(client,backup_root):
    """Explicit isolated rollback completion; no receipt is published."""
    return _finalize_transaction(client,backup_root,'rollback')


def _publish_pending_file(stage,marker,client):
    # Windows rename fails if the destination already exists; never os.replace.
    # Do not silently use POSIX rename, which would overwrite another marker.
    if os.name!='nt':raise OSError('Pending publication currently requires Windows non-replacing rename.')
    safe_target(stage,client,for_write=True);safe_target(marker,client,for_write=True)
    os.rename(stage,marker)


class RetainedUserBackup:
    """Verified original copies, never owned by recovery-evidence cleanup.

    Root is an explicit, already-created caller choice, not transaction metadata.
    Only locked preparation/completion callers construct this internal handle.
    originals.json commits a complete copy set; manifest.json remains the legacy
    installation receipt and is published only after terminal destination checks.
    """
    def __init__(self,record,receipt,client,recovery_root,user_root):
        self.client=client;self.identity=record['client'];self.receipt=receipt
        self.root=_transaction_directory(user_root)
        _check_windows_link_support(self.root)
        for protected in (client,_transaction_directory(recovery_root)):
            if self.root.is_relative_to(protected) or protected.is_relative_to(self.root):
                raise ValueError('User backups must be separate from client and recovery directories.')
        self.root_identity=_recovery_root_identity(self.root)
        self.path=self.root/('transaction-'+record['id'])
        self.files=[(item['path'],item['original']) for item in record['files'] if item['existed']]
        # No new transaction/receipt schema: this separate index describes originals.
        self.index=json.dumps(dict(schema=1,transaction=record['id'],client=self.identity,
            record=_byte_description(json.dumps(record,sort_keys=True).encode('utf-8')),
            receipt=_byte_description(receipt),files=[dict(path=p,**d) for p,d in self.files]),
            sort_keys=True).encode('utf-8')
        if len(self.index)>MAX_TRANSACTION_BYTES:raise ValueError('Retained backup index exceeds limit.')
        self.directory_identity=None
        self.bindings=None

    def _guard(self):
        if client_identity(self.client)!=self.identity or _recovery_root_identity(self.root)!=self.root_identity:
            raise ValueError('Retained backup location or locked client changed.')
        safe_target(self.path,self.root)
        if self.directory_identity is not None:
            if _recovery_root_identity(self.path)!=self.directory_identity:
                raise ValueError('Retained backup set identity changed.')

    def verify(self,*,require_receipt=False):
        self._guard()
        directory_identity=_recovery_root_identity(self.path)
        checked=[]
        for relative,expected in self.files:
            raw,stamp=_read_preparation_file(self.path/relative,self.root)
            if _byte_description(raw)!=expected:raise ValueError('Retained original verification failed.')
            checked.append((relative,stamp))
        raw,stamp=_read_preparation_file(self.path/'originals.json',self.root,max_bytes=MAX_TRANSACTION_BYTES)
        if raw!=self.index:raise ValueError('Retained backup index is missing, conflicting or incomplete.')
        checked.append(('originals.json',stamp))
        if self.bindings is not None and checked!=self.bindings:
            raise ValueError('Retained backup files changed after verification.')
        if require_receipt:
            raw,_=_read_preparation_file(self.path/'manifest.json',self.root)
            if raw!=self.receipt:raise ValueError('Retained installation receipt verification failed.')
        self._guard()
        if _recovery_root_identity(self.path)!=directory_identity:raise ValueError('Retained backup set changed.')
        self.directory_identity=directory_identity;self.bindings=checked

    def publish_receipt(self):
        self.verify()
        stage=self.path/'.manifest.stage';target=self.path/'manifest.json'
        raw,_=_read_preparation_file(target,self.root,missing=True)
        if raw is not None:
            if raw!=self.receipt:raise ValueError('Conflicting retained installation receipt; preserved.')
        else:
            staged,stamp=_read_preparation_file(stage,self.root,missing=True)
            if staged is None:
                artifacts=[]
                _write_preparation_artifact(stage,self.root,self.receipt,artifacts,[])
                stamp=artifacts[-1]['verified_stamp']
            elif staged!=self.receipt:raise ValueError('Incomplete retained receipt stage; preserved.')
            self.verify()
            if _read_preparation_file(stage,self.root)!=(self.receipt,stamp):
                raise ValueError('Retained receipt stage changed.')
            _publish_pending_file(stage,target,self.root)
        self.verify(require_receipt=True)


def _prepare_retained_backup(prepared,user_root):
    """Under active preparation lock, preserve a unique set before any publication.

    Failed/partial sets are retained, without a published originals.json claiming
    completeness. No directory, file or prior backup set is ever reused/deleted.
    """
    if not prepared._active or threading.get_ident()!=prepared._thread or prepared.ownership!='temporary':
        raise ValueError('Retained backup creation requires active temporary preparation.')
    record=validate_transaction(prepared._record_bytes,prepared._client,prepared._recovery)
    saved=RetainedUserBackup(record,prepared._receipt_bytes,prepared._client,prepared._backup_root,user_root)
    saved._guard();saved.path.mkdir()  # Exclusive UUID set; no collision fallback.
    saved.directory_identity=_recovery_root_identity(saved.path)
    artifacts=[];directories=[]
    for item in record['files']:
        if not item['existed']:continue
        saved._guard()
        raw,_=_read_preparation_file(prepared._recovery/item['backup'],prepared._backup_root)
        if _byte_description(raw)!=item['original']:raise ValueError('Recovery original changed before user backup.')
        _write_preparation_artifact(saved.path/item['path'],saved.root,raw,artifacts,directories)
    stage=saved.path/'.originals.stage'
    _write_preparation_artifact(stage,saved.root,saved.index,artifacts,directories)
    for entry in artifacts:
        saved._guard()
        if _read_preparation_file(entry['path'],entry['root'])!=(entry['expected'],entry['verified_stamp']):
            raise ValueError('Retained copy changed before index publication.')
    _publish_pending_file(stage,saved.path/'originals.json',saved.root)
    saved.verify()
    return saved


class PreparedTransaction(dict):
    """Temporary evidence with an explicit, one-way retention transition.

    Mapping fields remain compatible with M2A inspection callers. Publication
    uses private immutable bytes/ownership records, never the mutable mapping.
    Only the creating thread, inside the preparation context/lock, may publish.
    """
    def __init__(self,record,record_bytes,receipt_bytes,recovery,client,backup_root,artifacts,directories,jobs):
        super().__init__(record=record,record_bytes=record_bytes,receipt_bytes=receipt_bytes,recovery=recovery)
        self._record_bytes=record_bytes;self._receipt_bytes=receipt_bytes
        self._recovery=recovery;self._client=client;self._backup_root=backup_root
        self._artifacts=artifacts;self._directories=directories;self._jobs=jobs
        self._state='temporary';self._active=True;self._thread=threading.get_ident()

    @property
    def ownership(self):return self._state

    def retain_user_backup(self,root):
        """Explicit opt-in; the caller owns this history beyond context exit."""
        return _prepare_retained_backup(self,root)

    def publish_pending(self):
        if not self._active or threading.get_ident()!=self._thread:
            raise ValueError('Publication requires the active preparation context and owning thread.')
        if self._state!='temporary':raise ValueError('Evidence publication has already been attempted; preserve it.')
        if os.name!='nt':raise OSError('Pending publication currently requires Windows non-replacing rename.')
        record=validate_transaction(self._record_bytes,self._client,self._recovery)
        status=_inspect_pending_locked(self._client,self._backup_root)
        if status['state']!='none':raise ValueError('Pending evidence already exists or is uncertain; preserve it.')
        for entry in self._artifacts:
            if _read_preparation_file(entry['path'],entry['root'])!=(entry['expected'],entry['verified_stamp']):
                raise ValueError('Preparation artifact changed before publication.')
        for _,target,original,stamp,_ in self._jobs:
            if _read_preparation_file(target,self._client,missing=True)!=(original,stamp):
                raise ValueError('Addon changed before evidence publication.')
        marker=dict(schema=1,id=record['id'],client=record['client'],
                    backup_root=_recovery_root_identity(self._backup_root),transaction=_byte_description(self._record_bytes))
        raw=json.dumps(marker,sort_keys=True).encode('utf-8')
        _validate_pending(raw,self._client,self._backup_root)
        # From BEFORE the first publication write, even BaseException unwinding
        # must retain backups. Any failed attempt stays ambiguous, never temporary.
        self._state='ambiguous'
        _write_preparation_artifact(self._recovery/'transaction.json',self._backup_root,self._record_bytes,self._artifacts,self._directories)
        _write_preparation_artifact(self._recovery/'receipt.pending',self._backup_root,self._receipt_bytes,self._artifacts,self._directories)
        stage=self._client/f'.wf-addon-pending-{record["id"]}.stage'
        _write_preparation_artifact(stage,self._client,raw,self._artifacts,self._directories)
        for entry in self._artifacts:
            if _read_preparation_file(entry['path'],entry['root'])!=(entry['expected'],entry['verified_stamp']):
                raise ValueError('Evidence changed before pending publication; preserve it.')
        _publish_pending_file(stage,self._client/PENDING_NAME,self._client)
        status=_inspect_pending_locked(self._client,self._backup_root)
        if (status['state']!='valid' or status['record']!=record
            or any(entry['stage'][1] is None for entry in status['destinations'])):
            raise ValueError('Pending publication could not be verified; preserve recovery evidence.')
        self._state='published'
        return status


@contextmanager
def prepare_transaction(payload,client,selected,backup_root):
    """Explicit, scoped foundation API; NOT called by install/GUI/CLI.

    Holds the shared lock through preparation, caller inspection and cleanup.
    Yields in-memory metadata/receipt bytes and verified temporary artifacts.
    Temporary artifacts are cleaned on exit; explicit publication transfers them
    to retained evidence. No completed receipt or destination file is published.
    """
    with _transaction_client_lock(client) as (canonical,identity):
        with _prepare_transaction_locked(payload,canonical,selected,backup_root,identity) as prepared:
            yield prepared


@contextmanager
def _prepare_transaction_locked(payload,client,selected,backup_root,identity):
    """Internal preparation context; caller owns the pinned client lock."""
    if client_identity(client)!=identity:raise ValueError("Locked client identity changed before preparation.")
    payload=Path(payload).resolve(strict=True)
    backup_root=_transaction_directory(backup_root)
    _check_windows_link_support(backup_root)
    if backup_root.is_relative_to(client) or client.is_relative_to(backup_root):
        raise ValueError('Recovery directory must be separate from the game folder.')
    if _inspect_pending_locked(client,backup_root)['state']!='none':
        raise ValueError('Pending evidence already exists or is uncertain; preserve it.')
    selected=set(selected)
    if not selected or not selected<=set(ADDONS):raise ValueError('Select known Forever addons.')
    expanded=selected|({'WFCore'} if selected&{'WFStorage','WFProfessions'} else set())
    if 'WFCore' in expanded:check_legacy(client)
    metadata=package_metadata(payload,expanded)
    if set(metadata)!=expanded&PINNED_ADDONS:
        raise ValueError('Preparation requires pinned addon package identities.')
    expected_files={addon:dict(info['files']) for addon,info in metadata.items()}
    jobs=[];total=0
    for addon in sorted(expanded):
        sources=package_files(payload,addon)
        expected=expected_files.get(addon)
        if expected is not None:
            collected=[source.relative_to(payload/addon).as_posix() for source in sources]
            # Per-file hashes cannot detect members omitted by a changed enumeration.
            if len(collected)!=len(expected) or set(collected)!=set(expected):
                raise ValueError('Addon package incomplete or changed during preparation.')
        for source in sources:
            relative=source.relative_to(payload).as_posix()
            raw,_=_read_preparation_file(source,payload)
            if expected is not None and hashlib.sha256(raw).hexdigest()!=expected[source.relative_to(payload/addon).as_posix()]:
                raise ValueError('Addon package changed during preparation.')
            target=client/'Interface/AddOns'/relative
            original,stamp=_read_preparation_file(target,client,missing=True)
            total+=len(raw)+(len(original) if original is not None else 0)
            if len(jobs)>=MAX_TRANSACTION_FILES or total>MAX_TRANSACTION_TOTAL_BYTES:
                raise ValueError('Preparation exceeds transaction limits.')
            jobs.append((relative,target,original,stamp,raw))
    jobs.sort(key=lambda job:job[0].endswith('.toc'))
    identifier=uuid.uuid4().hex
    recovery=backup_root/('prepare-'+identifier)
    # Existing receipt structure; planned UTF-8/LF bytes are kept in memory only.
    receipt=dict(client=str(client),selected=sorted(expanded),packages=metadata,
                 files=[dict(path=str(t.relative_to(client)),sha256=hashlib.sha256(raw).hexdigest())
                        for _,t,_,_,raw in jobs])
    receipt_bytes=json.dumps(receipt,indent=2).encode('utf-8')
    record=dict(schema=1,id=identifier,client=identity,destination='Interface/AddOns',
                selected=sorted(selected),expanded=sorted(expanded),
                packages={name:{key:metadata[name][key] for key in ('source_commit','archive_sha256')}
                          for name in sorted(metadata)},files=[],
                receipt=dict(path='manifest.json',**_byte_description(receipt_bytes)))
    for index,(relative,_,original,_,raw) in enumerate(jobs):
        record['files'].append(dict(path=relative,existed=original is not None,
            original=_byte_description(original) if original is not None else None,
            replacement=_byte_description(raw),backup=relative if original is not None else None,
            stage=relative.rsplit('/',1)[0]+f'/.wf-{identifier}-{index}.stage'))
    record_bytes=json.dumps(record,sort_keys=True).encode('utf-8')
    # Preflight limits before any artifact creation; validate again at its actual root.
    validate_transaction(record_bytes,client,backup_root)
    artifacts=[];directories=[];error=None;prepared=None
    try:
        safe_target(recovery,backup_root)
        recovery.mkdir()  # Unique transaction directory; never reuse existing artifacts.
        directories.append((recovery,backup_root,None))
        info=recovery.stat(follow_symlinks=False)
        directories[-1]=(recovery,backup_root,_file_stamp(info)[:2])
        validate_transaction(record_bytes,client,recovery)
        # Finish and verify every original backup before creating any replacement stage.
        for relative,_,original,_,_ in jobs:
            if original is not None:
                _write_preparation_artifact(recovery/relative,backup_root,original,artifacts,directories)
        for item,(_,_,_,_,raw) in zip(record['files'],jobs):
            _write_preparation_artifact(client/'Interface/AddOns'/item['stage'],client,raw,artifacts,directories)
        for entry in artifacts:
            raw,stamp=_read_preparation_file(entry['path'],entry['root'])
            if raw!=entry['expected'] or stamp!=entry['verified_stamp']:
                raise ValueError('Preparation artifact changed before completion.')
        for _,target,original,stamp,_ in jobs:
            if _read_preparation_file(target,client,missing=True)!=(original,stamp):
                raise ValueError('Addon changed during preparation.')
        if client_identity(client)!=identity:raise ValueError('Game folder changed during preparation.')
        validate_transaction(record_bytes,client,recovery)
        prepared=PreparedTransaction(record,record_bytes,receipt_bytes,recovery,client,backup_root,artifacts,directories,jobs)
        yield prepared
    except Exception as exc:
        error=exc
        raise
    finally:
        if prepared is not None:prepared._active=False
        if prepared is None or prepared.ownership=='temporary':
            failures=_cleanup_preparation(artifacts,directories)
            if failures:raise TransactionPreparationError(error,failures) from error


def _apply_transaction_files(status,client,backup_root,identity):
    """Isolated forward writes; published originals remain available for recovery."""
    _verify_terminal_destinations(status,'rollback')
    for item,observed in zip(status['record']['files'],status['destinations']):
        if client_identity(client)!=identity:raise ValueError('Locked client identity changed.')
        _check_recovery_inputs(status,item,observed,client,backup_root)
        stage,content,stamp=observed['stage']
        if content is None or _byte_description(content)!=item['replacement']:
            raise ValueError('Verified replacement stage is unavailable.')
        # Checks above include reopened stage bytes/identity, original bytes or
        # absence, backup integrity and pending/client/root bindings. The paths
        # below come only from validated metadata and the pinned canonical client.
        target=client/'Interface/AddOns'/item['path']
        safe_target(stage,client,for_write=True);safe_target(target,client,for_write=True)
        if _file_stamp(stage.stat(follow_symlinks=False))!=stamp:
            raise ValueError('Replacement stage identity changed before use.')
        target_stamp=_file_stamp(target.stat(follow_symlinks=False)) if target.exists() else None
        if target_stamp!=observed['stamp']:
            raise ValueError('Destination identity changed before replacement; preserved.')
        os.replace(stage,target)
        installed,_=_read_preparation_file(target,client)
        if _byte_description(installed)!=item['replacement']:
            raise ValueError('Replacement contents could not be verified.')


def execute_transaction(payload,client,selected,backup_root,*,retained_backup_root=None):
    """Isolated executor; retain one canonical lock, including on service calls."""
    result=None
    try:
        with _transaction_client_lock(client) as (canonical,identity):
            result=_execute_transaction_locked(payload,canonical,selected,backup_root,identity,
                                               retained_backup_root=retained_backup_root)
        return result
    except Exception as exc:
        return dict(state='blocked' if result is None else 'finalization_pending',
                    phase='preparation' if result is None else result['phase'],
                    reason='Transaction lock or operation could not be verified; review before retrying.',error=exc)


def _execute_transaction_locked(payload,canonical,selected,backup_root,identity,*,retained_backup_root=None,observer=None):
    """Existing executor body; caller holds the pinned client lock through return."""
    phase='preparation';prepared=None;retained=None
    def result(**values):
        values['phase']=phase
        if retained is not None:values['retained_backup']=retained.path
        return values
    try:
        backup_root=_transaction_directory(backup_root)
        pending=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
        if pending['state']!='none':
            return result(state='blocked',reason='Pending installation evidence requires review before starting.',inspection=pending)
        with _prepare_transaction_locked(payload,canonical,selected,backup_root,identity) as prepared:
            if retained_backup_root is not None:
                phase='retained_backup'
                user_root=_transaction_directory(retained_backup_root)
                package_root=Path(payload).resolve(strict=True)
                if user_root.is_relative_to(package_root) or package_root.is_relative_to(user_root):
                    raise ValueError('User backups must be separate from package contents.')
                retained=prepared.retain_user_backup(user_root)
            phase='publication'
            prepared.publish_pending()
            if observer is not None:
                observer.begin(_inspect_pending_locked(canonical,backup_root,locked_identity=identity))
            phase='replacement'
            status=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
            if status['state']!='valid':raise ValueError('Published evidence could not be revalidated.')
            if retained is not None:retained.verify()
            if observer is not None:observer.check()
            _apply_transaction_files(status,canonical,backup_root,identity)
            phase='finalization'
            if retained is None:
                completion=_finalize_transaction_locked(canonical,backup_root,identity,'installation')
            else:
                completion=_finalize_transaction_locked(canonical,backup_root,identity,'installation',retained=retained,observer=observer)
            if completion['state']=='installation_complete' and not completion['failures']:
                return result(state='installation_complete',reason='Installation and receipt verified; evidence retired.',completion=completion)
            return result(state='finalization_pending',reason='Installation finalization requires review; preserve remaining evidence.',completion=completion)
    except Exception as exc:
        if phase=='replacement':
            # An exception may occur after the last replacement actually
            # succeeded. Do not roll back fully installed bytes for a
            # verification/finalization failure; inspect before deciding.
            try:
                current=_inspect_pending_locked(canonical,backup_root,locked_identity=identity)
                if current['state']=='valid':
                    try:_verify_terminal_destinations(current,'installation')
                    except ValueError:pass
                    else:
                        return result(state='finalization_pending',reason='Installed files verified; finalization remains pending.',error=exc,inspection=current)
                recovery=_recover_pending_locked(canonical,backup_root,identity)
                if recovery['state']=='rollback_complete':
                    completion=_finalize_transaction_locked(canonical,backup_root,identity,'rollback',observer=observer)
                    if completion['state']=='rollback_complete' and not completion['failures']:
                        return result(state='rollback_complete',reason='Installation failed; exact original files restored and evidence retired.',error=exc,recovery=recovery,completion=completion)
                    return result(state='recovery_pending',reason='Original files restored; rollback finalization requires review.',error=exc,recovery=recovery,completion=completion)
                return result(state='recovery_pending',reason='Recovery remains unresolved; preserve all evidence.',error=exc,recovery=recovery)
            except Exception as recovery_error:
                return result(state='recovery_pending',reason='Recovery remains unresolved; preserve all evidence.',error=exc,recovery_error=recovery_error)
        evidence_retained=prepared is not None and prepared.ownership!='temporary'
        state='finalization_pending' if phase=='finalization' else ('recovery_pending' if evidence_retained else 'blocked')
        reason=('Retained user backup could not be prepared; no addon files were replaced. Preserve partial backup sets.'
                if phase=='retained_backup' else 'Transaction could not complete; preserve any remaining evidence.')
        return result(state=state,reason=reason,error=exc)


class AddonInstallError(OSError):
    """Installation failure with a verified rollback outcome and retained evidence."""
    def __init__(self,installation_error,backup,rollback_failures):
        self.installation_error=installation_error
        self.backup=backup
        self.rollback_failures=tuple(rollback_failures)
        self.rollback_complete=not self.rollback_failures
        outcome=('Installation failed, but original files were restored.' if self.rollback_complete else
                 'Installation failed and rollback was incomplete. Some addon files may remain changed. '
                 'Keep the saved backups and review recovery before installing again.')
        # Original exceptions remain available to callers and in the exception
        # chain. Display only types and relative package paths, not OS messages
        # that may contain private absolute paths.
        details='Installation error: '+type(installation_error).__name__+'. Backup: '+backup.name+'.'
        if self.rollback_failures:
            details+=' Recovery failures: '+', '.join(path+' ('+type(error).__name__+')' for path,error in self.rollback_failures)+'.'
        super().__init__(outcome+' '+details)


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
    toc=safe_target(Path(client)/'Interface/AddOns/WFCore/WFCore.toc',client,for_write=True)
    if not toc.exists():return
    text=toc.read_text(encoding='utf-8-sig')
    if re.search(r'^##\s*Version:\s*0\.6(?:\.|\s|$)',text,re.M|re.I) or re.search(r'^\s*(?:Bags|BankUI|InventoryUI)\.lua\s*$',text,re.M|re.I):
        raise ValueError('Older combined Core installation detected. A separate migration is required; no files changed.')


def game_running():
    result=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,check=True,creationflags=0x08000000)
    return any(row and row[0].lower() in ('wow.exe','wowb.exe') for row in csv.reader(result.stdout.splitlines()))


def _check_windows_link_support(root):
    """Do not trust possibly partial network/unknown-provider link metadata."""
    if os.name!='nt':return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetVolumePathNameW.argtypes=(wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD)
    kernel.GetVolumePathNameW.restype=wintypes.BOOL
    kernel.GetDriveTypeW.argtypes=(wintypes.LPCWSTR,)
    kernel.GetDriveTypeW.restype=wintypes.UINT
    kernel.GetVolumeInformationW.argtypes=(wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR,wintypes.DWORD)
    kernel.GetVolumeInformationW.restype=wintypes.BOOL
    volume=ctypes.create_unicode_buffer(32768);filesystem=ctypes.create_unicode_buffer(128)
    message='Cannot verify addon hard-link safety here. Choose a local NTFS, FAT/FAT32 or exFAT game folder.'
    if not kernel.GetVolumePathNameW(str(root),volume,len(volume)):raise ValueError(message)
    if kernel.GetDriveTypeW(volume.value) not in (2,3):raise ValueError(message)  # Local removable/fixed only.
    if not kernel.GetVolumeInformationW(volume.value,None,0,None,None,None,filesystem,len(filesystem)):raise ValueError(message)
    # NTFS exposes link counts; FAT/exFAT do not support hard links. Other
    # providers (including ReFS) remain blocked until separately verified.
    if filesystem.value.upper() not in ('NTFS','FAT','FAT32','EXFAT'):raise ValueError(message)


def safe_target(path,root,*,for_write=False):
    path=Path(path);root=Path(root).resolve(strict=True)
    if not path.resolve().is_relative_to(root):raise ValueError('Addon path escapes the selected game folder.')
    for parent in (path,*path.parents):
        if parent==root:break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):raise ValueError('Linked addon directories are not supported.')
    if for_write:
        _check_windows_link_support(root)
        try:info=path.stat(follow_symlinks=False)
        except FileNotFoundError:return path  # A new file is allowed; other stat errors propagate.
        if not stat.S_ISREG(info.st_mode):raise ValueError('Addon destination must be a regular file: '+path.relative_to(root).as_posix())
        links=getattr(info,'st_nlink',None)
        if type(links) is not int or links<1:
            raise ValueError('Cannot verify addon file link count. Check filesystem access before installing.')
        if links!=1:
            raise ValueError('Hard-linked addon file is not supported: '+path.relative_to(root).as_posix()+
                             '. Preserve the linked files and use an independent addon copy before installing.')
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
            if addon not in ('WFCore','WFStorage','WFProfessions') or source.name!='branding':raise ValueError('Unexpected addon payload directory.')
            for asset in source.iterdir():
                safe_target(asset,payload)
                if not asset.is_file():raise ValueError('Unexpected addon branding file.')
                raw=asset.read_bytes()
                prefix={'WFCore':'wfcompanion','WFStorage':'forever-storage','WFProfessions':'forever-professions'}[addon]
                if addon=='WFProfessions' and asset.name=='README.md':
                    raw.decode('utf-8-sig')
                elif addon!='WFCore' and asset.name==prefix+'-logo.png':
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid addon branding image.')
                elif asset.name==prefix+'-icon.tga':
                    # Reviewed uncompressed RGBA icon, optional standard footer.
                    dimension=64 if addon=='WFProfessions' else 128
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
    with _transaction_client_lock(client) as (canonical,identity):
        pending=_inspect_production_pending_locked(canonical,identity)
        if pending['state']!='none':
            code={'valid':'recovery_pending','invalid':'recovery_invalid','ambiguous':'recovery_ambiguous'}
            raise InstallationGuardError(code.get(pending['state'],'recovery_invalid')) from pending.get('error')
        if client_identity(canonical)!=identity:raise InstallationGuardError('client_identity_changed')
        return _install_locked(payload,canonical,selected,backup_root,check_game=check_game)


def _install_locked(payload,client,selected,backup_root,*,check_game=False):
    # Keep the existing replacement/receipt/exception rollback sequence intact.
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
            target=safe_target(client/'Interface'/'AddOns'/source.relative_to(payload),client,for_write=True)
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
            safe_target(target,client,for_write=True)
            if (target.read_bytes() if target.exists() else None)!=before[target]:raise ValueError('Addon changed while preparing installation.')
            target.parent.mkdir(parents=True,exist_ok=True);written.append(target);target.write_bytes(raw)
            if target.read_bytes()!=raw:raise ValueError('Addon copy verification failed.')
        manifest={'client':str(client),'selected':sorted(selected),'packages':metadata,'files':[{ 'path':str(t.relative_to(client)), 'sha256':hashlib.sha256(raw).hexdigest()} for _,t,raw in jobs]}
        (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    except Exception as installation_error:
        installed={target:raw for _,target,raw in jobs}
        failures=[]
        for target in reversed(written):
            try:
                raw=before[target]
                safe_target(target,client,for_write=True)
                current=target.read_bytes() if target.exists() else None
                if current==raw:continue  # Failed before writing, or already restored.
                # Do not overwrite external edits or remove externally changed
                # new files. Ambiguous partial writes also require manual recovery.
                if current!=installed[target]:raise OSError('Addon changed before rollback; preserved for manual recovery.')
                if raw is None:target.unlink()
                else:target.write_bytes(raw)
                if (target.read_bytes() if target.exists() else None)!=raw:raise OSError('Addon rollback verification failed.')
            except Exception as recovery_error:
                failures.append((target.relative_to(client/'Interface/AddOns').as_posix(),recovery_error))
        raise AddonInstallError(installation_error,backup,failures) from installation_error
    return manifest
