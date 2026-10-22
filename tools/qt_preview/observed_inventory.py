"""Atomic, separate addon observations. Never writes manual inventory or plans."""
from copy import deepcopy
from pathlib import Path
import json
import os
import time
from storage import write_json
from character_links import LinkStore,key
from inventory_sync_plan import plan_sync


def raw(path):return path.read_bytes() if path.exists() else None


class ObservationStore:
    def __init__(self,directory):
        self.path=Path(directory).resolve()/'addon_inventory.json';self.original=raw(self.path);self.ledger={}
        if self.original is None:return
        if len(self.original)>5_000_000:raise ValueError('Saved addon inventory is too large.')
        document=json.loads(self.original)
        if not isinstance(document,dict) or document.get('version')!=1 or not isinstance(document.get('locations'),list):raise ValueError('Invalid addon inventory file; preserved.')
        for entry in document['locations']:
            if not isinstance(entry,dict):raise ValueError('Invalid addon location.')
            profile,scope=entry.get('profile'),entry.get('scope');record=entry.get('record')
            if not isinstance(profile,str) or not profile or scope not in ('bags','bank') or (profile,scope) in self.ledger or not isinstance(record,dict):raise ValueError('Invalid addon location.')
            value=record.get('identity')
            if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k] for k in ('source','environment','realm','guid','version','build','name')) or value['environment'] not in ('Test','Live') or type(value.get('interface')) is not int:raise ValueError('Invalid saved source identity.')
            if any(type(record.get(k)) is not int or not 0<=record[k]<=9999999999 for k in ('started','finished')) or record['started']>record['finished']:raise ValueError('Invalid observation times.')
            if not isinstance(record.get('build'),str) or not isinstance(record.get('rows'),list):raise ValueError('Invalid observed items.')
            seen=set()
            for pair in record['rows']:
                if not isinstance(pair,list) or len(pair)!=2 or any(type(n) is not int or not 1<=n<=2147483647 for n in pair) or pair[0] in seen:raise ValueError('Invalid observed item total.')
                seen.add(pair[0])
            record['rows']=tuple(tuple(pair) for pair in record['rows']);self.ledger[(profile,scope)]=record

    def save(self,candidate):
        if raw(self.path)!=self.original:raise ValueError('Addon observations changed outside this check; retrying later.')
        if candidate==self.ledger:return False
        payload={'version':1,'locations':[dict(profile=p,scope=s,record=r) for (p,s),r in sorted(candidate.items())]}
        write_json(self.path,payload);self.ledger=deepcopy(candidate);self.original=raw(self.path);return True


def prepare(directory,cache,profiles):
    """Worker produces a candidate; the UI thread rechecks conflicts before saving."""
    store=ObservationStore(directory);links=LinkStore(directory);candidate=deepcopy(store.ledger);decisions=[];signatures={}
    for source,(signature,observations) in cache.items():
        source_key=os.path.normcase(str(Path(source).resolve()))
        relevant=[e for e in links.records['links'] if e['identity']['source']==source_key]
        if not relevant:continue
        identities={}
        for entry in relevant:
            owner=entry['identity']['guid'];matches=[o for o in observations if o.owner==owner and o.schema==2]
            if matches:
                obs=matches[0]
                identities[owner]=dict(entry['identity'],realm=obs.realm,version=obs.client_version,interface=obs.interface,name=obs.label,build=obs.build)
        candidate,result=plan_sync(observations,identities,links.records['links'],candidate,profiles=profiles,now=int(time.time()),allowed_builds={'70532'})
        decisions.extend(result);signatures[source]=signature
    return store,links,candidate,tuple(decisions),signatures


def apply_prepared(data,prepared,expected_profiles):
    store,links,candidate,decisions,signatures=prepared
    if raw(data.profile_store.path)!=expected_profiles or data.profiles!=data.saved_profiles:
        raise ValueError('Character profiles changed during the check; retained previous observations.')
    if raw(links.path)!=links.original:raise ValueError('Character links changed during the check; retrying later.')
    for source,signature in signatures.items():
        stat=Path(source).stat()
        if (stat.st_mtime_ns,stat.st_size)!=signature:raise ValueError('Addon save changed during the check; retrying later.')
    # Observations have their own store and never replace manual counts. Applied
    # unsaved inventory edits pause persistence until the user resolves them.
    if 'Inventory & Bank' in data.dirty:raise ValueError('Unsaved applied inventory edits: addon updates paused.')
    changed=store.save(candidate)
    return changed,decisions
