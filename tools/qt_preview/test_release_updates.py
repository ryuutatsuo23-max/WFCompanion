from copy import deepcopy
from pathlib import Path
import hashlib
import io
import tempfile
import unittest
from unittest.mock import patch
import release_updates as r


def release():
    return {'tag_name':'v0.2.0','draft':False,'prerelease':False,'assets':[{'name':name,'size':size,'browser_download_url':f'https://github.com/{r.REPOSITORY}/releases/download/v0.2.0/{name}'} for name,size in ((r.ASSET,3),(r.ASSET+'.sha256',90))]}


class UpdatesTests(unittest.TestCase):
    def test_only_expected_stable_newer_release(self):
        doc=release();self.assertEqual(r.candidate(doc)['version'],'v0.2.0')
        for field in ('draft','prerelease'):
            bad=deepcopy(doc);bad[field]=True;self.assertIsNone(r.candidate(bad))
        self.assertIsNone(r.candidate(doc,'0.2.0'))
        for tag in ('v0.3.0-beta','../../bad','v1.2','v01.2.3'):
            bad=deepcopy(doc);bad['tag_name']=tag
            with self.assertRaises(ValueError):r.candidate(bad)
        bad=deepcopy(doc);bad['assets'][0]['browser_download_url']='https://other.example/setup.exe'
        with self.assertRaises(ValueError):r.candidate(bad)

    def test_verified_download_and_corruption_preserve_installed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            digest=hashlib.sha256(b'exe').hexdigest();checksum=(digest+'  '+r.ASSET+'\n').encode()
            with patch.object(r,'request',side_effect=[io.BytesIO(checksum),io.BytesIO(b'exe')]):
                path=r.download(r.candidate(release()),tmp);self.assertEqual(path.read_bytes(),b'exe')
            with patch.object(r,'request',side_effect=[io.BytesIO(checksum),io.BytesIO(b'bad')]):
                with self.assertRaises(ValueError):r.download(r.candidate(release()),tmp)
            self.assertEqual(path.read_bytes(),b'exe');self.assertFalse(list(Path(tmp).glob('*.part')))
