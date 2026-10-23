from pathlib import Path
import tempfile
import unittest
import json
import hashlib
import zipfile
from stage_addon_packages import stage


class PackageStageTests(unittest.TestCase):
    def test_exact_archive_and_tamper_rejection_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'core.zip';data=b'## Version: 0.7.0\n'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('WFCore/WFCore.toc',data)
            info=dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files={'WFCore.toc':hashlib.sha256(data).hexdigest()})
            manifest=root/'pins.json';manifest.write_text(json.dumps(dict(schema=1,packages={'WFCore':info})))
            stage({'WFCore':archive},root/'stage',manifest)
            self.assertEqual((root/'stage/addons/WFCore/WFCore.toc').read_bytes(),data)
            archive.write_bytes(archive.read_bytes()+b'tampered')
            with self.assertRaisesRegex(ValueError,'Archive digest'):stage({'WFCore':archive},root/'rejected',manifest)
            self.assertFalse((root/'rejected').exists())
