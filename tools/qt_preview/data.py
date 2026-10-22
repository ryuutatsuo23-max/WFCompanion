"""Existing domain models, isolated Qt saves, and a one-time verified copy.

Nothing in this module writes to the legacy source directory. A staging folder
and manifest make interrupted imports recoverable without merging stale files.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from app import SOURCE
from storage import ProfileStore, write_json
from professions import PlanStore, ProfessionPlan
from inventory import InventoryStore, InventoryBook
from gear import GearStore, GearWishlist
from inventory_filters import InventoryFilterStore
from gear_filters import GearFilterStore
from search_filters import SearchFilterStore
from inventory_undo import InventoryUndoStore
from gear_undo import GearUndoStore
from local_journal import LocalStore, validate_journal
from playstyles import Playstyles
from display_settings import DEFAULT, validate_preferences

STATE = Path(__file__).resolve().parent / 'state'
SAVE_FILES = ('profiles.json', 'planning.json', 'inventory.json', 'gear_wishlist.json',
              'inventory_filters.json', 'gear_filters.json', 'item_search_filters.json',
              'inventory_undo.json', 'gear_undo.json', 'auction_prices.json',
              'display_settings.json', 'window_placement.json')


def import_legacy(source=SOURCE / 'state', destination=STATE):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Qt and backup data folders must be separate.')
    if destination.exists():
        if any(destination.iterdir()) and not (destination / 'qt_import_manifest.json').exists():
            raise ValueError('Existing Qt data has no import manifest; preserved without merging. Inspect this folder before retrying.')
        if (destination / 'qt_import_manifest.json').exists():
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='qt-import-', dir=destination.parent))
    manifest = dict(version=1, imported_at=datetime.now(timezone.utc).isoformat(), source=str(source), files={})
    try:
        for name in SAVE_FILES:
            for filename in (name, name.replace('.json', '.previous.json')):
                original = source / filename
                if not original.exists():
                    continue
                if original.is_symlink() or original.stat().st_size > 5_000_000:
                    raise ValueError(f'Cannot safely copy {filename}; source preserved.')
                raw = original.read_bytes()
                (staging / filename).write_bytes(raw)
                digest = hashlib.sha256(raw).hexdigest()
                if hashlib.sha256((staging / filename).read_bytes()).hexdigest() != digest or original.read_bytes() != raw:
                    raise ValueError('Source changed during import; retry after closing the backup tool.')
                manifest['files'][filename] = digest
        for filename, digest in manifest['files'].items():
            if hashlib.sha256((source / filename).read_bytes()).hexdigest() != digest:
                raise ValueError('Source changed during import; original data preserved.')
        (staging / 'qt_import_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        if destination.exists():
            destination.rmdir()  # Only the verified empty target; never recursive.
        staging.rename(destination)
    finally:
        if staging.exists() and staging.parent == destination.parent and staging.name.startswith('qt-import-'):
            shutil.rmtree(staging)


def validate_qt(data):
    if not isinstance(data, dict) or set(data) not in ({'version', 'classic_fonts', 'font_override'}, {'version', 'classic_fonts', 'font_override','experience_mode'}) or data['version'] != 1:
        raise ValueError('Unsupported Qt font settings.')
    if type(data['classic_fonts']) is not bool or data['font_override'] not in ('', 'Friz Quadrata TT', 'Arial Narrow', 'Morpheus', 'Skurri'):
        raise ValueError('Invalid Qt font choice.')
    if data.get('experience_mode','Easy') not in ('Easy','Advanced'):
        raise ValueError('Choose Easy or Advanced mode.')


class Data:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.profile_store = ProfileStore(self.directory)
        self.profiles, self.active = self.profile_store.load()
        self.profile_bytes = self.profile_store.path.read_bytes() if self.profile_store.path.exists() else None
        self.plans_store, self.inventory_store, self.gear_store = PlanStore(directory), InventoryStore(directory), GearStore(directory)
        self.plans = self.plans_store.load()
        self.inventories = self.inventory_store.load()
        self.gear = self.gear_store.load()
        self.playstyles = Playstyles(directory)
        self.inventory_filters, self.gear_filters = InventoryFilterStore(directory), GearFilterStore(directory)
        self.search_filters = SearchFilterStore(directory)
        self.inventory_undo, self.gear_undo = InventoryUndoStore(directory), GearUndoStore(directory)
        self.display = LocalStore(directory, 'display_settings.json', DEFAULT, validate_preferences)
        self.prices = LocalStore(directory, 'auction_prices.json', {'version': 1, 'characters': {}}, validate_journal)
        self.qt = LocalStore(directory, 'qt_fonts.json', {'version': 1, 'classic_fonts': True, 'font_override': ''}, validate_qt)
        self.saved_profiles = deepcopy(self.profiles)
        self.dirty = set()

    @property
    def profile(self):
        return next(p for p in self.profiles if p.id == self.active)

    @property
    def plan(self):
        return self.plans.setdefault(self.active, ProfessionPlan())

    @property
    def inventory(self):
        return self.inventories.setdefault(self.active, InventoryBook())

    @property
    def wishlist(self):
        if self.playstyles.active(self.active) != 'General': return self.playstyles.book(self.active)
        return self.gear.setdefault(self.active, GearWishlist())

    def set_wishlist(self,book):
        if self.playstyles.active(self.active)=='General': self.gear[self.active]=book
        else: self.playstyles.books[(self.active,self.playstyles.active(self.active))]=book

    def gear_dirty_key(self):
        return 'Gear wishlist' if self.playstyles.active(self.active)=='General' else ('Gear wishlist',self.active,self.playstyles.active(self.active))

    def errors(self):
        return [store.error for store in (self.profile_store, self.plans_store, self.inventory_store, self.gear_store,
                self.inventory_filters, self.gear_filters, self.search_filters, self.inventory_undo,
                self.gear_undo, self.display, self.prices, self.qt, self.playstyles.store) if store.error]

    def save_profiles(self):
        current = self.profile_store.path.read_bytes() if self.profile_store.path.exists() else None
        if current != self.profile_bytes:
            raise ValueError('Profiles changed outside Qt. Reopen before saving; external changes preserved.')
        self.profile_store.save(self.profiles, self.active)
        self.profile_bytes = self.profile_store.path.read_bytes()
        self.saved_profiles = deepcopy(self.profiles)
        self.dirty.discard('Profiles & Rules')

    def require_profile_saved(self):
        if self.profile_store.error:
            raise ValueError(self.profile_store.error)
        if self.active not in {p.id for p in self.saved_profiles}:
            raise ValueError('Save this new character in Profiles & Rules before saving its records.')

    def save_records(self, kind):
        self.require_profile_saved()
        if kind=='Gear wishlist' and self.playstyles.active(self.active)!='General':
            self.playstyles.save_gear(self.active)
            self.dirty.discard(self.gear_dirty_key())
            return
        store, values = {'Inventory & Bank': (self.inventory_store, self.inventories),
                         'Gear wishlist': (self.gear_store, self.gear),
                         'Crafting': (self.plans_store, self.plans)}[kind]
        if set(values) - {p.id for p in self.saved_profiles}:
            raise ValueError('Save all new characters in Profiles & Rules before saving their records.')
        store.save(values)
        self.dirty.discard(kind)
