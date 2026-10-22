import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'offline_preview'))
from catalogue import ItemCatalogue


class PublicPackageTests(unittest.TestCase):
    def test_empty_public_catalogue_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sample=root/'sample.json'
            sample.write_text(json.dumps(dict(version=1,revision='public-empty-v1',items=[],coverage_note='No bundled catalogue.')))
            catalogue=ItemCatalogue(root,sample_path=sample)
            self.assertEqual(catalogue.revision,'public-empty-v1')
            self.assertEqual(catalogue.coverage_note,'No bundled catalogue.')
            catalogue.close()


if __name__=='__main__':unittest.main()
