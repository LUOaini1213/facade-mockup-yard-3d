"""Fail when tracked files carry local machine paths (standard library only).

Text files: any user-home path (drive:\\Users\\<name>, /home/<name>, /Users/<name>), any absolute
path on a non-system drive (D: to Z:) and the old local workspace folder name are
errors. Installation defaults such as C:\\Program Files\\Rhino 8 are allowed.

Binary files: drive-letter paths are counted in ASCII and UTF-16LE. The two
committed Rhino files still embed their historical export folder; they are listed
in PENDING_REGENERATION with their exact counts until the owner re-exports them
(the native file needs licensed Rhino). Any other binary hit, or a changed count,
fails, so a regenerated clean file must also remove its entry here.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'
SYSTEM_DIRS = ('program files', 'program files (x86)', 'programdata', 'windows')
TEXT_SUFFIXES = {'.py', '.md', '.json', '.csv', '.txt', '.yml', '.yaml', '.html', '.js', '.cjs', '.css',
                 '.bat', '.ids', '.xml', '.toml', '.cfg', '.ini', ''}
TEXT_PATTERNS = [
    re.compile(r'(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]+(?:users|documents and settings)[\\/]+[^\\/\s]'),
    re.compile(r'(?<![A-Za-z0-9])[D-Z]:\\{1,2}[A-Za-z0-9 _.()\-]{2,}\\'),
    re.compile(r'(?<![A-Za-z0-9])[D-Z]:/[A-Za-z0-9 _.()\-]{2,}/'),
    re.compile(r'(?<![\w.~-])/home/[A-Za-z0-9_.\-]+/'),
    re.compile(r'(?<![\w.~-])/Users/[A-Za-z0-9_.\-]+/'),
    re.compile(r'(?i)claude[ _]student'),
]
SEGMENT = rb'[A-Za-z0-9 _.()\-]{2,}'
BINARY_ASCII = re.compile(rb'(?<![A-Za-z0-9])[A-Za-z]:\\(' + SEGMENT + rb')\\')
BINARY_UTF16 = re.compile(rb'(?<![A-Za-z0-9]\x00)[A-Za-z]\x00:\x00\\\x00((?:[A-Za-z0-9 _.()\-]\x00){2,})\\\x00')
# Historical exports, regenerated only with licensed Rhino 8 (see README "Use Rhino 8").
PENDING_REGENERATION = {
    'model/vmu_site_future.3dm': 1,
    'model/vmu_site_future_native.3dm': 325,
}


def tracked_files(root):
    output = subprocess.run(['git', 'ls-files', '-z'], cwd=root, check=True, capture_output=True).stdout
    return [name for name in output.decode('utf-8').split('\0') if name]


def text_hits(text):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for pattern in TEXT_PATTERNS:
            match = pattern.search(line)
            if match:
                hits.append((number, match.group(0)))
                break
    return hits


def binary_hits(data):
    count = 0
    for match in BINARY_ASCII.finditer(data):
        count += match.group(1).decode('ascii').lower() not in SYSTEM_DIRS
    for match in BINARY_UTF16.finditer(data):
        count += match.group(1).decode('utf-16-le').lower() not in SYSTEM_DIRS
    return count


def scan(root, names, require_lfs=False, pending=None):
    pending = PENDING_REGENERATION if pending is None else pending
    errors, skipped, binaries = [], [], {}
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if data.startswith(LFS_POINTER):
            (errors if require_lfs else skipped).append(name + ': Git LFS pointer, content not fetched')
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and b'\0' not in data:
            for number, sample in text_hits(data.decode('utf-8', errors='replace')):
                errors.append(f'{name}:{number}: local path {sample!r}')
            continue
        count = binary_hits(data)
        if count or name in pending:
            binaries[name] = count
            if count != pending.get(name, 0):
                errors.append(f'{name}: {count} embedded local paths, expected {pending.get(name, 0)}'
                              + (' (regenerated? remove it from PENDING_REGENERATION)' if name in pending else ''))
    return {'passed': not errors, 'errors': errors, 'skipped': skipped,
            'binary_path_counts': binaries, 'pending_regeneration': sorted(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--require-lfs', action='store_true', help='treat unfetched LFS pointers as errors')
    parser.add_argument('paths', nargs='*', help='files to scan instead of every tracked file')
    args = parser.parse_args()
    names = args.paths or tracked_files(ROOT)
    report = scan(ROOT, names, args.require_lfs)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
