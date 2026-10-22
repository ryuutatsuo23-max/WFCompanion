import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import incremental_updates as incremental
import release_updates as releases
from test_release_updates import release


class IncrementalTests(unittest.TestCase):
    def fixture(self,root):
        p=root/'WFCompanion.exe';p.write_bytes(b'base')
        rows={'WFCompanion.exe':dict(size=4,sha256=hashlib.sha256(b'base').hexdigest())}
        doc=release()
        for suffix,size in (('.json',1),('.exe',2),('.exe.sha256',90)):
            name='WFCompanion-patch-from-0.1.11'+suffix
            doc['assets'].append(dict(name=name,size=size,browser_download_url=f'https://github.com/{releases.REPOSITORY}/releases/download/v0.2.0/{name}'))
        meta=dict(schema=1,base='0.1.11',target='0.2.0',asset='WFCompanion-patch-from-0.1.11.exe',size=2,sha256='a'*64,files=rows)
        raw=json.dumps(meta).encode();doc['assets'][2]['size']=len(raw)
        return releases.candidate(doc,'0.1.11'),meta,raw

    def test_matching_base_selects_small_package_and_modified_base_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release,meta,raw=self.fixture(root)
            with patch.object(releases,'request',return_value=io.BytesIO(raw)):
                self.assertIn('asset',incremental.select(release,root))
            (root/'WFCompanion.exe').write_bytes(b'edit')
            with patch.object(releases,'request',return_value=io.BytesIO(raw)):
                self.assertIs(incremental.select(release,root),release)
            (root/'WFCompanion.exe').unlink()
            with patch.object(releases,'request',return_value=io.BytesIO(raw)):
                self.assertIs(incremental.select(release,root),release)

    def test_hostile_paths_and_metadata_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release,meta,raw=self.fixture(root)
            for name in ('../escape','/absolute','_internal/../escape','_internal/CON','_internal/file:stream','_internal/name.'):
                bad=dict(meta,files={**meta['files'],name:dict(size=0,sha256='a'*64)})
                self.assertFalse(incremental.matches(root,bad),name)
            with patch.object(releases,'request',return_value=io.BytesIO(b'broken')):
                self.assertIs(incremental.select(release,root),release)
            with patch.object(releases,'request',side_effect=OSError('offline')):
                self.assertIs(incremental.select(release,root),release)

    def test_patch_failure_downloads_full_and_recovery_marker_skips_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release,meta,raw=self.fixture(root)
            selected={'asset':'patch'}
            with patch.object(incremental.sys,'frozen',True,create=True), patch.object(incremental,'select',return_value=selected), patch.object(releases,'download',side_effect=[ValueError('bad checksum'),root/'full.exe']) as download:
                self.assertEqual(incremental.fetch(release,root),root/'full.exe')
                self.assertIs(download.call_args_list[1].args[0],release)
            (root/'full-update-required').write_text('recovery')
            with patch.object(incremental.sys,'frozen',True,create=True), patch.object(incremental,'select') as select, patch.object(releases,'download',return_value=root/'full.exe'):
                incremental.fetch(release,root);select.assert_not_called()

    def test_patch_download_pins_checksum(self):
        chosen=dict(version='v0.2.0',asset='WFCompanion-patch-from-0.1.11.exe',sha256='a'*64)
        for key,suffix in (('installer',''),('checksum','.sha256')):chosen[key]=(f'https://github.com/{releases.REPOSITORY}/releases/download/v0.2.0/'+chosen['asset']+suffix,2)
        with tempfile.TemporaryDirectory() as tmp, patch.object(releases,'request',return_value=io.BytesIO(('b'*64+'  '+chosen['asset']+'\n').encode())):
            with self.assertRaisesRegex(ValueError,'disagreement'):releases.download(chosen,tmp)


if __name__=='__main__':unittest.main()
