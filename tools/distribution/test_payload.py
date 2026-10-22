import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from audit_payload import allowed,audit


class PayloadTests(unittest.TestCase):
    def test_allowlist_excludes_personal_and_unrelated_files(self):
        for path in ('tools/qt_preview/state/profiles.json','User files/secret.lua',
                     'tools/offline_preview/theme_art/font.ttf','tools/addon_preview/preview.py',
                     'tools/qt_preview/test_companion.py','addons/Bagnon/main.lua',
                     'addons/WFCore/WTF/save.lua','../addons/WFCore/Core.lua','/addons/WFCore/Core.lua'):
            self.assertFalse(allowed(path),path)
        for path in ('tools/qt_preview/companion.py','tools/offline_preview/model.py',
                     'addons/WFCore/Core.lua','addons/WFStressProbe/WFStressProbe.toc'):
            self.assertTrue(allowed(path),path)

    def test_tracked_audit_has_runtime_and_recommended_addon(self):
        names=('tools/qt_preview/companion.py','addons/WFCore/WFCore.toc')
        with tempfile.TemporaryDirectory() as directory:
            for name in names:
                path=Path(directory)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('audit fixture')
            with patch('audit_payload.subprocess.check_output',return_value=('\0'.join(names)+'\0').encode()):
                result=audit(directory)
                (Path(directory)/names[0]).unlink()
                with self.assertRaises(FileNotFoundError):audit(directory)
        paths={row['path'] for row in result['files']}
        self.assertIn('tools/qt_preview/companion.py',paths)
        self.assertIn('addons/WFCore/WFCore.toc',paths)
        self.assertTrue(all(len(row['sha256'])==64 for row in result['files']))


if __name__=='__main__':unittest.main()
