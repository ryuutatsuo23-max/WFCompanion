"""Explicit source-scoped links only; never links by name or applies inventory."""
from copy import deepcopy
from pathlib import Path
import json
import os
from uuid import uuid4
from core_observations import CoreData,decode
from storage import write_json
from model import default_profile


def identity(path,guid,environment):
    if environment not in ('Test','Live'):raise ValueError('Choose Test or Live explicitly.')
    path=Path(path).resolve();before=path.stat()
    if before.st_size>64*1024*1024:raise ValueError('Source file is too large.')
    with path.open('rb') as stream:raw=stream.read(64*1024*1024+1)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed; check it again.')
    decode(raw)  # Reuse the current strict producer/client/schema validator.
    db=CoreData(raw.decode('utf-8-sig'),max_nodes=4_000_000).decode()
    character=db['characters'].get(guid)
    if not character:raise ValueError('Character is no longer in this source.')
    source=character['identity'];client=character['client']
    realm=source.get('realm','').strip()
    if not realm:raise ValueError('Realm was not recorded; a safe character link cannot be saved yet.')
    name=' '.join(source.get(k,'') for k in ('firstName','lastName')).strip() or guid
    return dict(source=os.path.normcase(str(path)),environment=environment,realm=realm,
                guid=guid,version=client['version'],interface=client['interface'],
                build=str(client.get('build','Unknown')),name=name)


def key(value):
    return tuple(value[k] for k in ('source','environment','realm','guid','version','interface'))


class LinkStore:
    def __init__(self,directory):
        self.path=Path(directory).resolve()/'character_links.json'
        self.original=self.path.read_bytes() if self.path.exists() else None
        if self.original is not None and len(self.original)>1_000_000:raise ValueError('Character links file is too large.')
        self.records=json.loads(self.original) if self.original is not None else {'version':1,'links':[]}
        if not isinstance(self.records,dict) or self.records.get('version')!=1 or not isinstance(self.records.get('links'),list):
            raise ValueError('Unsupported character links file; preserved.')
        seen=set();destinations=set()
        for entry in self.records['links']:
            if not isinstance(entry,dict) or not isinstance(entry.get('identity'),dict) or not isinstance(entry.get('profile'),str):
                raise ValueError('Invalid character link; preserved.')
            value=entry['identity']
            if any(not isinstance(value.get(k),str) or not value[k] for k in ('source','environment','realm','guid','version','build','name')) or type(value.get('interface')) is not int:
                raise ValueError('Invalid source identity; preserved.')
            if value['environment'] not in ('Test','Live') or key(value) in seen or entry['profile'] in destinations:
                raise ValueError('Conflicting character links; preserved.')
            seen.add(key(value));destinations.add(entry['profile'])

    def linked(self,value):
        return next((e['profile'] for e in self.records['links'] if key(e['identity'])==key(value)),None)

    def save(self,data,value,destination):
        profile=next((p for p in data.saved_profiles if p.id==destination),None)
        if profile is None:raise ValueError('Choose an existing saved profile.')
        check_profiles(data)
        if destination.startswith('capture-') and destination!='capture-'+value['guid']:
            raise ValueError('That imported profile belongs to a different GUID.')
        previous=self.linked(value)
        if previous and previous!=destination:raise ValueError('This source is already linked to another profile.')
        if any(e['profile']==destination and key(e['identity'])!=key(value) for e in self.records['links']):
            raise ValueError('This profile already belongs to a different source, client or environment. Create a separate profile.')
        if (self.path.read_bytes() if self.path.exists() else None)!=self.original:
            raise ValueError('Links changed outside this review. Reopen it before saving.')
        if previous:return
        candidate=deepcopy(self.records);candidate['links'].append(dict(identity=value,profile=destination))
        write_json(self.path,candidate);self.records=candidate;self.original=self.path.read_bytes()


def check_profiles(data):
    if data.profile_store.error:raise ValueError(data.profile_store.error)
    if data.profiles!=data.saved_profiles or 'Profiles & Rules' in data.dirty:
        raise ValueError('Save applied profile changes first. Unfinished editor fields will be kept.')
    if (data.profile_store.path.read_bytes() if data.profile_store.path.exists() else None)!=data.profile_bytes:
        raise ValueError('Profiles changed outside the companion; reopen before continuing.')


def create_profile(data,value):
    check_profiles(data)
    profile=default_profile();profile.id='linked-'+uuid4().hex;profile.name=value['name']
    profile.validate()  # Class is left unspecified; the addon does not record it.
    candidate=[*data.profiles,profile]
    data.profile_store.save(candidate,data.active)
    data.profiles=candidate;data.saved_profiles=deepcopy(candidate)
    data.profile_bytes=data.profile_store.path.read_bytes()
    return profile.id
