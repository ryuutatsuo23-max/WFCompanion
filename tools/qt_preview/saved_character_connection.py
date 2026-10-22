"""Explicitly remembered Beta source, with GUID-scoped profiles and no inventory writes."""
from pathlib import Path
from character_links import LinkStore, identity, create_profile, check_profiles
from local_journal import LocalStore
from profession_observations import ObservationCache
from game_data_review import discover
from core_observations import CoreData, decode


def core_identities(directory):
    path=Path(directory)/'WFCore.lua'
    before=path.stat()
    if before.st_size>64*1024*1024:raise ValueError('Core save is too large.')
    with path.open('rb') as stream:raw=stream.read(64*1024*1024+1)
    if len(raw)>64*1024*1024:raise ValueError('Core save is too large.')
    decode(raw)
    db=CoreData(raw.decode('utf-8-sig'),max_nodes=4_000_000).decode()
    values=[identity(path,guid,'Test') for guid in db['characters']]
    after=path.stat()
    if (before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size):
        raise ValueError('Core save changed during discovery; waiting for the next check.')
    return values


def signature(directory):
    result=[]
    for name in ('WFCore.lua','DataStore.lua','DataStore_Crafts.lua'):
        path=Path(directory)/name
        try:
            stat=path.stat();result.append((name,stat.st_mtime_ns,stat.st_size))
        except FileNotFoundError:result.append((name,None,None))
    return tuple(result)


def validate(value):
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('directory'), str) or len(value['directory']) > 4096):
        raise ValueError('Invalid saved-character connection.')
    if type(value.get('automatic',True)) is not bool:raise ValueError('Invalid automatic connection preference.')


class SavedCharacterConnection:
    def __init__(self, host):
        self.host = host
        self.store = LocalStore(host.data.directory, 'saved_character_connection.json',
                                {'version': 1, 'directory': ''}, validate)
        self.accepted_signature=None
        self.pending_signature=None

    def connect(self, directory, remember=True):
        if self.store.error:
            raise ValueError(self.store.error)
        current = self.store.path.read_bytes() if self.store.path.exists() else None
        if current != self.store.original:
            raise ValueError('Connection changed outside the companion; reopen before continuing.')
        directory=Path(directory).resolve()
        if '_classic_beta_' not in directory.parts:raise ValueError('Automatic connection requires a Beta saved-data folder.')
        before=signature(directory)
        identities=core_identities(directory)
        cache = ObservationCache()
        has_professions=any((directory/name).exists() for name in ('DataStore.lua','DataStore_Crafts.lua'))
        if has_professions and not cache.refresh(directory):
            raise ValueError(cache.error)
        data = self.host.data
        check_profiles(data)
        links = LinkStore(data.directory)
        # Validate the complete batch before adding anything. No name-based merge.
        for char in cache.accepted['characters'] if cache.accepted else []:
            if not char['guid'] or not char.get('label'):
                raise ValueError('A saved character has no verified name/GUID mapping.')
            value = next((v for v in identities if v['guid']==char['guid']),None)
            if value is None:raise ValueError('Profession character is not in the Core save yet.')
            if (value['name'], value['realm']) != (char['label']['name'], char['label']['realm']):
                raise ValueError('Core and DataStore character identity disagree.')
        if signature(directory)!=before:raise ValueError('Saved files changed during discovery; waiting for the next check.')
        for value in identities:
            destination = links.linked(value)
            if destination is not None and destination not in {p.id for p in data.saved_profiles}:
                raise ValueError('A linked profile is missing; review its link first.')
        for value in identities:
            links = LinkStore(data.directory)
            destination = links.linked(value)
            if destination is not None:
                continue
            destination = create_profile(data, value)
            links.save(data, value, destination)
        if remember:
            self.store.save({'version': 1, 'directory': str(directory),'automatic':True})
        if cache.accepted:self.host.profession_observations = cache
        if hasattr(self.host, 'character'):
            combo=self.host.character
            combo.blockSignals(True);combo.clear()
            for profile in data.profiles:combo.addItem(profile.name,profile.id)
            combo.setCurrentIndex(combo.findData(data.active));combo.blockSignals(False)
        self.host.character_overview.refresh()
        self.accepted_signature=(str(directory),before)
        if hasattr(self.host,'banner') and self.host.banner.text().startswith('Saved-character connection needs attention: '):
            self.host.banner.clear();self.host.banner.hide()
        return cache

    def forget(self):
        """Stop startup reads without deleting profiles, links or cached observations."""
        self.store.save({'version': 1, 'directory': '', 'automatic':False})

    def start(self):
        from PySide6.QtCore import QTimer
        self.timer=QTimer(self.host);self.timer.setInterval(30000)
        self.timer.timeout.connect(self.poll);self.timer.start()
        QTimer.singleShot(0,self.restore)

    def source(self):
        if self.store.error:raise ValueError(self.store.error)
        if not self.store.data.get('automatic',True):return None
        if self.store.data['directory']:return self.store.data['directory']
        folders=sorted({str(p.parent) for p in discover() if '_classic_beta_' in p.parts})
        if len(folders)>1:raise ValueError('Several Beta account folders found. Choose the account in Read professions save.')
        return folders[0] if folders else None

    def poll(self):
        if getattr(self.host,'testing',False):return
        # Do not replace the cache or rebuild controls while a review is open.
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget() is not None:return
        if not self.host.character_overview.game_data_monitor.enabled:return
        try:
            directory=self.source()
            if not directory:return
            current=(str(directory),signature(directory))
            if current==self.accepted_signature:return
            if current!=self.pending_signature:
                self.pending_signature=current;return
            self.connect(directory,remember=False)
        except (ValueError,OSError,KeyError,TypeError) as exc:self.notice(exc)

    def notice(self,exc):
        self.host.banner.setText('Saved-character connection needs attention: '+str(exc))
        self.host.banner.show()

    def restore(self):
        if getattr(self.host, 'testing', False):
            return
        try:
            directory=self.source()
            if directory:self.connect(directory, remember=False)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.notice(exc)
