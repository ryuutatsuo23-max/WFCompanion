from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import tempfile
import unittest
from data import Data
from saved_character_connection import SavedCharacterConnection
from character_links import LinkStore


class ConnectionTests(unittest.TestCase):
    def test_actual_core_save_parsing_without_datastore(self):
        SAVE = b'WFCoreDB={schema=1,producer="WFCore",characters={\n["Player-1-ABC"]={identity={guid="Player-1-ABC",firstName="Same",lastName="Name"},\nclient={version="1.60.1",interface=16001},locations={bags={latest={schema=1,addonVersion="0.2.0",owner="Player-1-ABC",scope="bags",accessible=true,coverage="attempted",unknownSlots=1,\nstartedAt=1792600000,finishedAt=1792600001,client={version="1.60.1",interface=16001,build="70009"},\ncontainers={{id=0,slots=2}},slots={{bag=0,slot=1,state="observed",itemID=2589,count=3},{bag=0,slot=2,state="unknown"}}}}}},\n["Player-1-DEF"]={identity={guid="Player-1-DEF",firstName="Same",lastName="Name"},client={version="1.60.1",interface=16001},locations={}}\n}}'
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'_classic_beta_';folder.mkdir()
            raw=SAVE.replace(b'firstName="Same"',b'realm="Test Realm",firstName="Same"')
            (folder/'WFCore.lua').write_bytes(raw)
            host=SimpleNamespace(data=Data(Path(tmp)),character_overview=SimpleNamespace(refresh=Mock()))
            service=SavedCharacterConnection(host)
            service.connect(folder,remember=False)
            self.assertEqual({e['identity']['guid'] for e in LinkStore(tmp).records['links']},{'Player-1-ABC','Player-1-DEF'})
            self.assertEqual((folder/'WFCore.lua').read_bytes(),raw)
            self.assertFalse((Path(tmp)/'addon_inventory.json').exists())

    def test_discovery_needs_no_saved_preference_but_rejects_multiple_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=SavedCharacterConnection(SimpleNamespace(data=Data(Path(tmp))))
            first=Path(tmp)/'_classic_beta_/WTF/Account/Example/SavedVariables/WFCore.lua'
            second=first.parent.parent.parent/'Other/SavedVariables/WFCore.lua'
            with patch('saved_character_connection.discover',return_value=[first]):
                self.assertEqual(service.source(),str(first.parent))
            with patch('saved_character_connection.discover',return_value=[first,second]):
                with self.assertRaisesRegex(ValueError,'Several'):service.source()
            service.forget()
            with patch('saved_character_connection.discover') as discover:
                self.assertIsNone(service.source());discover.assert_not_called()

    def test_core_only_new_alt_without_professions_and_no_duplicate_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'_classic_beta_';folder.mkdir()
            data=Data(Path(tmp));host=SimpleNamespace(data=data,character_overview=SimpleNamespace(refresh=Mock()))
            service=SavedCharacterConnection(host)
            first=dict(source=str(folder/'WFCore.lua'),environment='Test',realm='Realm',guid='Player-999-ABC1',version='1.60.1',interface=16001,build='70532',name='Example')
            alt={**first,'guid':'Player-999-ABC2','name':'Another Example'}
            with patch('saved_character_connection.core_identities',return_value=[first]):service.connect(folder,remember=False)
            initial=len(data.profiles)
            with patch('saved_character_connection.core_identities',return_value=[first,alt]):
                service.connect(folder,remember=False);service.connect(folder,remember=False)
            self.assertEqual(len(data.profiles),initial+1)
            self.assertEqual(len(LinkStore(tmp).records['links']),2)
            self.assertFalse(service.store.path.exists())
            self.assertFalse((Path(tmp)/'addon_inventory.json').exists())

    def test_poll_waits_for_stable_save_and_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=SimpleNamespace(data=Data(Path(tmp)),character_overview=SimpleNamespace(game_data_monitor=SimpleNamespace(enabled=True)),banner=Mock())
            service=SavedCharacterConnection(host)
            with patch.object(service,'source',return_value=tmp),patch('saved_character_connection.signature',return_value=('new',)),patch('PySide6.QtWidgets.QApplication.activeModalWidget',return_value=None),patch.object(service,'connect') as connect:
                service.poll();connect.assert_not_called()
                service.poll();connect.assert_called_once_with(tmp,remember=False)
                service.accepted_signature=(tmp,('new',))
                service.poll();self.assertEqual(connect.call_count,1)

    def test_remember_idempotent_guid_links_and_preserve_manual_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Data(Path(tmp));original=list(data.profiles)
            data.profile_store.save(data.profiles,data.active)
            data.profile_bytes=data.profile_store.path.read_bytes()
            host=SimpleNamespace(data=data,character_overview=SimpleNamespace(refresh=Mock()))
            service=SavedCharacterConnection(host)
            folder=Path(tmp)/'_classic_beta_';folder.mkdir();(folder/'DataStore.lua').write_text('fixture')
            chars=[dict(guid='Player-999-ABC1',label=dict(name='Example',realm='Realm'))]
            cache=SimpleNamespace(accepted={'characters':chars},error='',refresh=lambda _:True)
            ident=dict(source=str(Path(tmp)/'WFCore.lua'),environment='Test',realm='Realm',guid='Player-999-ABC1',version='1.60.1',interface=16001,build='70532',name='Example')
            with patch('saved_character_connection.ObservationCache',return_value=cache),patch('saved_character_connection.core_identities',return_value=[ident]):
                service.connect(folder);service.connect(folder)
            self.assertEqual(len(data.profiles),len(original)+1)
            self.assertEqual(data.profiles[:len(original)],original)
            self.assertEqual(len(LinkStore(tmp).records['links']),1)
            self.assertEqual(service.store.data['directory'],str(folder.resolve()))
            self.assertFalse((Path(tmp)/'inventory.json').exists())
            self.assertFalse((Path(tmp)/'addon_inventory.json').exists())
            self.assertFalse((Path(tmp)/'planning.json').exists())
            profiles_before=data.profile_store.path.read_bytes()
            links_before=LinkStore(tmp).path.read_bytes()
            service.forget()
            self.assertEqual(service.store.data['directory'],'')
            self.assertEqual(data.profile_store.path.read_bytes(),profiles_before)
            self.assertEqual(LinkStore(tmp).path.read_bytes(),links_before)

    def test_startup_restores_remembered_source_and_keeps_last_cache_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=SimpleNamespace(data=Data(Path(tmp)),banner=Mock(),profession_observations=object())
            service=SavedCharacterConnection(host)
            service.store.save({'version':1,'directory':tmp})
            reopened=SavedCharacterConnection(host)
            with patch.object(reopened,'connect') as connect:
                reopened.restore()
                connect.assert_called_once_with(tmp,remember=False)
            previous=host.profession_observations
            with patch.object(reopened,'connect',side_effect=ValueError('Source unavailable')):
                reopened.restore()
            self.assertIs(host.profession_observations,previous)
            self.assertIn('Source unavailable',host.banner.setText.call_args.args[0])
            self.assertFalse((Path(tmp)/'character_links.json').exists())

    def test_external_connection_change_prevents_profile_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=SavedCharacterConnection(SimpleNamespace(data=Data(Path(tmp))))
            service.store.path.write_text('{"version":1,"directory":"changed"}')
            with patch('saved_character_connection.ObservationCache') as cache:
                with self.assertRaisesRegex(ValueError,'outside'):
                    service.connect(tmp)
                cache.assert_not_called()
            self.assertFalse((Path(tmp)/'character_links.json').exists())

    def test_mapping_conflict_leaves_profiles_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Data(Path(tmp));host=SimpleNamespace(data=data)
            original=data.profile_bytes
            folder=Path(tmp)/'_classic_beta_';folder.mkdir();(folder/'DataStore.lua').write_text('fixture')
            cache=SimpleNamespace(accepted={'characters':[dict(guid=None,label=None)]},error='',refresh=lambda _:True)
            with patch('saved_character_connection.ObservationCache',return_value=cache),patch('saved_character_connection.core_identities',return_value=[]):
                with self.assertRaises(ValueError):SavedCharacterConnection(host).connect(folder)
            self.assertEqual(data.profile_bytes,original)
            self.assertFalse((Path(tmp)/'character_links.json').exists())
