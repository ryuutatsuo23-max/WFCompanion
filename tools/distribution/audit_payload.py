"""Inventory candidate tracked release inputs without copying personal files.

This is an audit, not a public redistribution approval or an installer builder.
Run python -B tools/distribution/audit_payload.py. JSON is written to stdout.
"""
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import stat
import subprocess

ROOT=Path(__file__).resolve().parents[2]
# Source code and individual allowlisted assets, not executable bundles.
MAX_SOURCE_BYTES=64*1024*1024
ADDONS=('WFCore','WFStorage','WFProfessions','WFStressProbe','WFDisplayTest')
# Exact GUI runtime closure; CLI/setup keep their existing legacy entry points.
# Never collect the distribution tools directory recursively.
DISTRIBUTION_RUNTIME=('install_addons','addon_installation_service',
    'addon_installation_configuration','addon_installation_context',
    'addon_installation_gui','addon_operation_status')
ADDON_RUNTIME_SOURCES=tuple('tools/distribution/'+name+'.py' for name in DISTRIBUTION_RUNTIME)+(
    'tools/qt_preview/addon_recovery_dialog.py',)


def allowed(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:return False
    if name in ADDON_RUNTIME_SOURCES:return True
    if name in ('tools/qt_preview/artwork/forever-storage-transparent.png',
                'tools/qt_preview/artwork/forever-professions-transparent.png',
                'tools/qt_preview/artwork/README.md','tools/qt_preview/artwork/GPL-3.0.txt',
                'tools/qt_preview/artwork/STORAGE_SOURCE_NOTICES.md',
                'tools/qt_preview/artwork/PROFESSIONS_SOURCE_NOTICES.md'):return True
    if len(path.parts)==3 and path.parts[0]=='addons' and path.parts[1] in ADDONS:
        return path.suffix in ('.lua','.toc','.xml','.md') or path.name=='LICENSE' or (path.parts[1]=='WFProfessions' and path.name=='PACKAGE_SHA256.json')
    if name in ('addons/WFCore/branding/wfcompanion-icon.tga','addons/WFStorage/branding/forever-storage-logo.png','addons/WFStorage/branding/forever-storage-icon.tga','addons/WFProfessions/branding/forever-professions-logo.png','addons/WFProfessions/branding/forever-professions-icon.tga','addons/WFProfessions/branding/README.md','addons/WFProfessions/PACKAGE_SHA256.json'):return True
    if len(path.parts)==3 and path.parts[:2] in (('tools','qt_preview'),('tools','offline_preview')):
        return path.suffix=='.py' and not path.name.startswith(('test_','benchmark_','manual_'))
    return False


def payload_relative_path(name):
    """Name mapping only, not filesystem authorization. Consume via read_payload_source."""
    if not allowed(name):raise ValueError('Unapproved payload input.')
    if name in ADDON_RUNTIME_SOURCES and name.startswith('tools/distribution/'):
        return PurePosixPath(name).name
    return name


def _source_identity(info, *, directory=False):
    """Require real identities and a uniquely linked regular input, never guess."""
    attributes=getattr(info,'st_file_attributes',None if os.name=='nt' else 0)
    if type(attributes) is not int or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError('Reparse point')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('Unexpected file type')
    identity=[getattr(info,field,None) for field in ('st_dev','st_ino')]
    if any(type(value) is not int or value<=0 for value in identity):
        raise ValueError('Unavailable filesystem identity')
    if directory:return identity
    links=getattr(info,'st_nlink',None)
    if type(links) is not int or links!=1:raise ValueError('Ambiguous link ownership')
    # Python 3.12 Windows lstat/fstat differ in ctime semantics; birthtime is
    # explicit on both. Do not compare creation time with metadata change time.
    time_field='st_birthtime_ns' if os.name=='nt' else 'st_ctime_ns'
    metadata=[getattr(info,field,None) for field in ('st_size','st_mtime_ns',time_field)]
    if any(type(value) is not int or value<0 for value in metadata):
        raise ValueError('Unavailable file metadata')
    return identity+metadata+[links]


def _source_snapshot(root, path):
    # Include root and its ancestors: resolving a junction first would hide it.
    directories=[_source_identity(parent.lstat(),directory=True)
                 for parent in reversed(path.parents)]
    file_identity=_source_identity(path.lstat())
    if root.resolve(strict=True)!=root or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Source containment changed')
    return dict(directories=directories,file=file_identity)


def _check_source_filesystem(root):
    """Use the existing local-provider policy without importing package inputs.

    The transaction engine has the same NTFS/FAT/exFAT boundary, but importing
    install_addons here could execute an input before it has passed this audit.
    Both audit and collection use this one packaging-specific native query.
    """
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
    if not kernel.GetVolumePathNameW(str(root),volume,len(volume)):raise ValueError('Unavailable volume')
    if kernel.GetDriveTypeW(volume.value) not in (2,3):raise ValueError('Unsupported drive')
    if not kernel.GetVolumeInformationW(volume.value,None,0,None,None,None,filesystem,len(filesystem)):
        raise ValueError('Unavailable filesystem')
    if filesystem.value.upper() not in ('NTFS','FAT','FAT32','EXFAT'):raise ValueError('Unsupported filesystem')


def read_source(root, name, *, expected_identity=None, expected_sha256=None):
    """Read an owned package input, checking path and open-handle metadata twice.

    Windows stat/fstat supply native file identity and link-count information.
    Preserve the installer's local NTFS/FAT/exFAT provider policy; unsupported
    providers/query failures never fall back to a guessed single-link identity.
    No path or content check makes hostile concurrent filesystem changes atomic.
    """
    if not isinstance(name,str):raise ValueError('Invalid package-relative source.')
    relative=PurePosixPath(name)
    if (not name or relative.is_absolute() or relative.as_posix()!=name or
            any(part in ('.','..') or ':' in part or '\\' in part or
                part.endswith((' ','.')) or any(ord(c)<32 for c in part) for part in relative.parts)):
        raise ValueError('Invalid package-relative source.')
    try:
        root=Path(os.path.abspath(root));path=root.joinpath(*relative.parts)
        before=_source_snapshot(root,path)
        size=before['file'][2]
        if size>MAX_SOURCE_BYTES:raise ValueError('Package input exceeds size limit')
        _check_source_filesystem(root)
        if expected_identity is not None and before!=expected_identity:
            raise ValueError('Source identity changed')
        # Unbuffered: even underlying read-ahead must stay within this bound.
        with path.open('rb',buffering=0) as stream:
            if _source_identity(os.fstat(stream.fileno()))!=before['file']:
                raise ValueError('Source changed while opening')
            raw=stream.read(size+1)
            if _source_identity(os.fstat(stream.fileno()))!=before['file']:
                raise ValueError('Source changed while reading')
            if _source_snapshot(root,path)!=before:raise ValueError('Source path changed')
        if len(raw)!=before['file'][2]:raise ValueError('Incomplete source read')
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest()!=expected_sha256:
            raise ValueError('Source contents changed')
        return raw,before
    except FileNotFoundError:
        raise FileNotFoundError('Package input unavailable: '+name) from None
    except Exception:
        raise ValueError('Unsafe or changed package input: '+name) from None


def read_payload_source(root, name, **verification):
    """Authorize the source before returning a payload selection and its bytes."""
    destination=payload_relative_path(name)
    raw,identity=read_source(root,name,**verification)
    return destination,raw,identity


def audit(root=ROOT):
    root=Path(os.path.abspath(root))
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
    pins_path=root/'tools/distribution/addon_packages.json'
    try:pins_path.lstat()
    except FileNotFoundError:pins={}
    else:pins=json.loads(read_source(root,'tools/distribution/addon_packages.json')[0])['packages']
    result=[]
    for name in sorted(filter(allowed,tracked)):
        parts=PurePosixPath(name).parts
        if parts[0]=='addons' and parts[1] in pins and '/'.join(parts[2:]) not in pins[parts[1]]['files']:continue
        _,raw,identity=read_payload_source(root,name)
        result.append(dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),identity=identity))
    return {'stage':'source-audit-only','addons':list(ADDONS),'files':result,
            'excluded':'Personal saves, artwork/fonts, captures, third-party addons and catalogue data are not approved payloads.'}


if __name__=='__main__':print(json.dumps(audit(),indent=2))
