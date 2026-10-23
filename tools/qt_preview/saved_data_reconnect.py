"""Explicit relocation of a missing source; never match characters by name."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
from character_links import LinkStore, key, check_profiles
from storage import write_json


def missing_source(service):
    directory=service.store.data['directory']
    return bool(directory) and not (Path(directory)/'WFCore.lua').is_file()


def preview_reconnect(service,directory):
    before,identities,cache=service.preview(directory)
    if not missing_source(service):
        raise ValueError('The original save is available. Use its existing connection.')
    old=os.path.normcase(str((Path(service.store.data['directory'])/'WFCore.lua').resolve()))
    links=LinkStore(service.host.data.directory)
    previous=[e for e in links.records['links'] if os.path.normcase(str(Path(e['identity']['source']).resolve()))==old]
    if not previous:raise ValueError('No existing character links belong to this missing file.')
    # Source is the only identity component allowed to change.
    new={key(v)[1:]:v for v in identities}
    if len(new)!=len(identities) or set(new)!={key(e['identity'])[1:] for e in previous}:
        raise ValueError('This save does not contain the same linked characters, realms and client. Choose the moved account save; existing characters and plans are kept.')
    profiles={p.id for p in service.host.data.saved_profiles}
    if any(e['profile'] not in profiles for e in previous):raise ValueError('An existing linked profile is missing. Reconnect has been stopped.')
    if any(links.linked(v) is not None for v in identities):raise ValueError('The replacement source already has character links. Reconnect has been stopped to avoid merging profiles.')
    candidate=deepcopy(links.records)
    for entry in candidate['links']:
        if entry['profile'] in {e['profile'] for e in previous}:entry['identity']=new[key(entry['identity'])[1:]]
    token=(before,links.original,service.store.original)
    return token,identities,candidate,cache


def reconnect(service,directory,expected):
    token,identities,candidate,cache=preview_reconnect(service,directory)
    if token!=expected:raise ValueError('Saved files or character links changed since preview. Preview again before reconnecting.')
    check_profiles(service.host.data)
    links=LinkStore(service.host.data.directory)
    if links.original!=token[1]:raise ValueError('Character links changed; preview again.')
    # Persist an exact local recovery copy before changing either companion file.
    backup=Path(tempfile.mkdtemp(prefix='saved-data-reconnect-backup-',dir=service.host.data.directory))
    (backup/'character_links.json').write_bytes(links.original)
    (backup/'saved_character_connection.json').write_bytes(service.store.original)
    write_json(links.path,candidate)
    try:
        service.store.save(dict(version=1,directory=str(Path(directory).resolve()),automatic=True))
    except (OSError,ValueError):
        # Restore exact prior links if persisting the connection fails.
        temporary=links.path.with_suffix('.reconnect-restore')
        temporary.write_bytes(links.original);temporary.replace(links.path)
        raise
    service.accepted_signature=(str(Path(directory).resolve()),token[0])
    if cache.accepted:service.host.profession_observations=cache
    service.host.character_overview.refresh()
    if service.host.banner.text().startswith('Saved-character connection needs attention: '):
        service.host.banner.clear();service.host.banner.hide()
