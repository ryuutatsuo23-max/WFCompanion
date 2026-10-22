"""Explicitly remembered Beta source, with GUID-scoped profiles and no inventory writes."""
from pathlib import Path
from character_links import LinkStore, identity, create_profile, check_profiles
from local_journal import LocalStore
from profession_observations import ObservationCache


def validate(value):
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('directory'), str) or len(value['directory']) > 4096):
        raise ValueError('Invalid saved-character connection.')


class SavedCharacterConnection:
    def __init__(self, host):
        self.host = host
        self.store = LocalStore(host.data.directory, 'saved_character_connection.json',
                                {'version': 1, 'directory': ''}, validate)

    def connect(self, directory, remember=True):
        if self.store.error:
            raise ValueError(self.store.error)
        current = self.store.path.read_bytes() if self.store.path.exists() else None
        if current != self.store.original:
            raise ValueError('Connection changed outside the companion; reopen before continuing.')
        cache = ObservationCache()
        if not cache.refresh(directory):
            raise ValueError(cache.error)
        data = self.host.data
        check_profiles(data)
        links = LinkStore(data.directory)
        identities = []
        # Validate the complete batch before adding anything. No name-based merge.
        for char in cache.accepted['characters']:
            if not char['guid'] or not char.get('label'):
                raise ValueError('A saved character has no verified name/GUID mapping.')
            value = identity(Path(directory)/'WFCore.lua', char['guid'], 'Test')
            if (value['name'], value['realm']) != (char['label']['name'], char['label']['realm']):
                raise ValueError('Core and DataStore character identity disagree.')
            identities.append(value)
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
            self.store.save({'version': 1, 'directory': str(Path(directory).resolve())})
        self.host.profession_observations = cache
        if hasattr(self.host, 'character'):
            combo=self.host.character
            combo.blockSignals(True);combo.clear()
            for profile in data.profiles:combo.addItem(profile.name,profile.id)
            combo.setCurrentIndex(combo.findData(data.active));combo.blockSignals(False)
        self.host.character_overview.refresh()
        return cache

    def forget(self):
        """Stop startup reads without deleting profiles, links or cached observations."""
        self.store.save({'version': 1, 'directory': ''})

    def restore(self):
        if getattr(self.host, 'testing', False) or not self.store.data['directory']:
            return
        try:
            self.connect(self.store.data['directory'], remember=False)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.host.banner.setText('Saved-character connection needs attention: '+str(exc))
            self.host.banner.show()
