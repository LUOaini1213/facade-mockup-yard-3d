"""Mutation tests for checks/check_readme.py: a stale README figure or a moved private figure must fail."""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('check_readme', ROOT / 'checks' / 'check_readme.py')
check_readme = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_readme)
SIZED = ['vmu_cad.glb', 'vmu01_canopy.glb', 'vmu02.glb', 'vmu04.glb', 'vmu05.glb', 'site_ground.glb',
         'site_context.glb', 'vmu_site_future.3dm']


class ReadmeNumbers(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        for pattern in ['README.md', 'README.zh-CN.md', 'model/*.json', 'model/*.csv', 'renders/*.png', 'renders/rhino/*.png']:
            for path in ROOT.glob(pattern):
                target = self.root / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for name in SIZED:  # only the size is read; a sparse stand-in avoids copying 140 MB
            with (self.root / 'model' / name).open('wb') as stream:
                stream.truncate((ROOT / 'model' / name).stat().st_size)

    def tearDown(self):
        self.folder.cleanup()

    def edit(self, name, old, new):
        path = self.root / name
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding='utf-8')

    def test_committed_readmes_match_artifacts(self):
        report = check_readme.check(ROOT)
        self.assertTrue(report['passed'], report['errors'])
        self.assertTrue(check_readme.check(self.root)['passed'])

    def test_stale_readme_number_fails(self):
        self.edit('README.md', '2,222,589 valid triangles', '2,222,590 valid triangles')
        self.assertFalse(check_readme.check(self.root)['passed'])

    def test_stale_chinese_readme_number_fails(self):
        self.edit('README.zh-CN.md', '129 个闭合、106 个开放', '130 个闭合、106 个开放')
        self.assertFalse(check_readme.check(self.root)['passed'])

    def test_changed_artifact_fails(self):
        self.edit('model/vmu_site_future_geometry.json', '"solid": 101', '"solid": 102')
        self.assertFalse(check_readme.check(self.root)['passed'])

    def test_private_figure_outside_its_section_fails(self):
        self.edit('README.md', 'model, not BIM elements;', 'model, not BIM elements; plan fit within 0.053 m;')
        report = check_readme.check(self.root)
        self.assertFalse(report['passed'])
        self.assertTrue(any('0.053 m' in error for error in report['errors']))


if __name__ == '__main__':
    unittest.main()
