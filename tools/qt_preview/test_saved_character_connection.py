from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import tempfile
import unittest
from data import Data
from saved_character_connection import SavedCharacterConnection
from character_links import LinkStore


class ConnectionTests(unittest.TestCase):
    def test_remember_idempotent_guid_links_and_preserve_manual_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Data(Path(tmp));original=list(data.profiles)
            data.profile_store.save(data.profiles,data.active)
            data.profile_bytes=data.profile_store.path.read_bytes()
            host=SimpleNamespace(data=data,character_overview=SimpleNamespace(refresh=Mock()))
            service=SavedCharacterConnection(host)
            chars=[dict(guid='Player-999-ABC1',label=dict(name='Example',realm='Realm'))]
            cache=SimpleNamespace(accepted={'characters':chars},error='',refresh=lambda _:True)
            ident=dict(source=str(Path(tmp)/'WFCore.lua'),environment='Test',realm='Realm',guid='Player-999-ABC1',version='1.60.1',interface=16001,build='70532',name='Example')
            with patch('saved_character_connection.ObservationCache',return_value=cache),patch('saved_character_connection.identity',return_value=ident):
                service.connect(tmp);service.connect(tmp)
            self.assertEqual(len(data.profiles),len(original)+1)
            self.assertEqual(data.profiles[:len(original)],original)
            self.assertEqual(len(LinkStore(tmp).records['links']),1)
            self.assertEqual(service.store.data['directory'],str(Path(tmp).resolve()))
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
            cache=SimpleNamespace(accepted={'characters':[dict(guid=None,label=None)]},error='',refresh=lambda _:True)
            with patch('saved_character_connection.ObservationCache',return_value=cache):
                with self.assertRaises(ValueError):SavedCharacterConnection(host).connect(tmp)
            self.assertEqual(data.profile_bytes,original)
            self.assertFalse((Path(tmp)/'character_links.json').exists())
