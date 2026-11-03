"""Known-value tests for checks/scan_local_paths.py (standard library only)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('scan_local_paths', ROOT / 'checks' / 'scan_local_paths.py')
scan_local_paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_local_paths)

# Built from parts so this file does not itself contain a local path.
HOME = 'C:' + '\\' + 'Users' + '\\' + 'someone' + '\\' + 'repo'
OTHER_DRIVE = 'E:' + '\\' + 'work folder' + '\\' + 'model'
INSTALL = 'C:' + '\\' + 'Program Files' + '\\' + 'Rhino 8' + '\\' + 'System'


class LocalPathScan(unittest.TestCase):
    def run_scan(self, files, pending=None, require_lfs=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, data in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(data)
            return scan_local_paths.scan(root, list(files), require_lfs, {} if pending is None else pending)

    def test_text_paths_fail_and_install_defaults_pass(self):
        self.assertFalse(self.run_scan({'a.md': ('see ' + HOME).encode()})['passed'])
        self.assertFalse(self.run_scan({'a.py': ('x = r"' + OTHER_DRIVE + '"').encode()})['passed'])
        self.assertFalse(self.run_scan({'a.txt': b'log at /' + b'home/someone/run'})['passed'])
        self.assertFalse(self.run_scan({'a.json': ('"' + 'claude' + ' student"').encode()})['passed'])
        self.assertTrue(self.run_scan({'a.md': ('OIDN from ' + INSTALL).encode()})['passed'])
        self.assertTrue(self.run_scan({'a.md': b'see https://example.org/home/page and e.g. a:b'})['passed'])

    def test_binary_paths_are_counted_in_ascii_and_utf16(self):
        blob = b'\x00\x01' + OTHER_DRIVE.encode('utf-16-le') + b'\x00' + HOME.encode() + b'\x02' + INSTALL.encode('utf-16-le')
        report = self.run_scan({'m.3dm': blob})
        self.assertFalse(report['passed'])
        self.assertEqual(report['binary_path_counts'], {'m.3dm': 2})
        self.assertTrue(self.run_scan({'m.3dm': blob}, pending={'m.3dm': 2})['passed'])
        # A regenerated clean file must also drop its pending entry.
        self.assertFalse(self.run_scan({'m.3dm': b'\x00clean'}, pending={'m.3dm': 2})['passed'])
        self.assertTrue(self.run_scan({'m.3dm': INSTALL.encode('utf-16-le') + b'\x00'})['passed'])

    def test_lfs_pointer_is_skipped_unless_required(self):
        pointer = {'n.3dm': b'version https://git-lfs.github.com/spec/v1\noid sha256:0\nsize 1\n'}
        self.assertTrue(self.run_scan(pointer)['passed'])
        self.assertFalse(self.run_scan(pointer, require_lfs=True)['passed'])

    def test_repository_has_no_new_local_paths(self):
        report = scan_local_paths.scan(ROOT, scan_local_paths.tracked_files(ROOT))
        self.assertTrue(report['passed'], report['errors'])


if __name__ == '__main__':
    unittest.main()
