from pathlib import Path
import tempfile
import unittest
from build_incremental import compare


class IncrementalBuildTests(unittest.TestCase):
    def test_only_existing_application_files_can_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a';b=Path(tmp)/'b'
            for root in (a,b):
                (root/'_internal/payload').mkdir(parents=True)
                (root/'WFCompanion.exe').write_bytes(b'exe')
                (root/'_internal/python312.dll').write_bytes(b'runtime')
                (root/'_internal/payload/app.py').write_bytes(b'old')
            (b/'_internal/payload/app.py').write_bytes(b'new')
            self.assertEqual(compare(a,b)[2],['_internal/payload/app.py'])
            (b/'_internal/python312.dll').write_bytes(b'new runtime')
            with self.assertRaisesRegex(ValueError,'Runtime'):compare(a,b)
            (b/'_internal/python312.dll').write_bytes(b'runtime')
            (b/'new.txt').write_text('new')
            with self.assertRaisesRegex(ValueError,'Added or removed'):compare(a,b)


if __name__=='__main__':unittest.main()
