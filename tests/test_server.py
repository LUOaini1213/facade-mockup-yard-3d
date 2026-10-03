"""Real HTTP regressions; the server and every saved file live in a temp directory."""
import base64
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import shutil
import runpy
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(pixel=b'\xff\x00\x00\xff'):
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00' + pixel)) + chunk(b'IEND', b''))


def data_url(data):
    return b'data:image/png;base64,' + base64.b64encode(data)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='facade-http-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / 'serve.py', self.root / 'serve.py')
        (self.root / 'index.html').write_text('isolated viewer', encoding='utf-8')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.log = (self.root / 'server.log').open('wb')
        self.addCleanup(self.log.close)
        self.proc = subprocess.Popen([sys.executable, '-B', str(self.root / 'serve.py'), str(self.port)],
                                     cwd=self.root, stdout=self.log, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'MOCKUP_PT_DENOISE': '0'})
        self.addCleanup(self.stop)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.2):
                    break
            except OSError:
                if self.proc.poll() is not None:
                    self.fail((self.root / 'server.log').read_text(errors='replace'))
                time.sleep(.02)
        else:
            self.fail('server did not start')

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=5)

    def request(self, body=None, *, path='/save?name=shot.png', headers=None, method='POST'):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def raw(self, fields, body=b''):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as sock:
            sock.sendall((f'POST /save?name=shot.png HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                          + fields + '\r\n').encode('ascii') + body)
            sock.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(sock)
            response.begin()
            return response.status, response.read()

    def assert_no_save(self):
        self.assertFalse((self.root / 'renders' / 'shot.png').exists())

    def test_valid_png_and_static_viewer_without_optional_dependencies(self):
        status, headers, body = self.request(data_url(png()))
        self.assertEqual(status, 200)
        self.assertEqual(body, b'ok')
        self.assertEqual((self.root / 'renders' / 'shot.png').read_bytes(), png())
        self.assertIn('X-MOCKUP-Serve', headers)
        self.assertTrue(headers['X-MOCKUP-PT-Denoise'].startswith('0;'))
        self.assertEqual(self.request(method='GET', path='/index.html')[2], b'isolated viewer')
        self.assertEqual(self.request(b'payload', path='/pt_denoise')[0], 501)

    def test_non_png_is_rejected(self):
        self.assertEqual(self.request(data_url(b'not a PNG'))[0], 400)
        self.assert_no_save()

    def test_wrong_mime_is_rejected(self):
        self.assertEqual(self.request(data_url(png()).replace(b'image/png', b'image/jpeg'))[0], 400)
        self.assert_no_save()

    def test_invalid_base64_is_rejected(self):
        self.assertEqual(self.request(b'data:image/png;base64,%%%')[0], 400)
        self.assert_no_save()

    def test_non_ascii_body_is_a_response_not_disconnect(self):
        self.assertEqual(self.request(b'\xff')[0], 400)
        self.assert_no_save()

    def test_truncated_png_is_rejected(self):
        self.assertEqual(self.request(data_url(png()[:-3]))[0], 400)
        self.assert_no_save()

    def test_crc_corruption_is_rejected(self):
        corrupt = bytearray(png())
        corrupt[29] ^= 1
        self.assertEqual(self.request(data_url(corrupt))[0], 400)
        self.assert_no_save()

    def test_existing_render_cannot_be_overwritten(self):
        folder = self.root / 'renders'
        folder.mkdir()
        old = png(b'\x00\xff\x00\xff')
        (folder / 'shot.png').write_bytes(old)
        self.assertEqual(self.request(data_url(png()))[0], 409)
        self.assertEqual((folder / 'shot.png').read_bytes(), old)

    def test_cross_origin_post_is_rejected(self):
        self.assertEqual(self.request(data_url(png()), headers={'Origin': 'https://example.org'})[0], 403)
        self.assert_no_save()

    def test_same_origin_post_succeeds(self):
        self.assertEqual(self.request(data_url(png()), headers={'Origin': f'http://127.0.0.1:{self.port}'})[0], 200)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(self.request(data_url(png()), headers={'Host': f'example.org:{self.port}'})[0], 403)
        self.assert_no_save()

    def test_bad_lengths_are_http_errors(self):
        for length in ['nope', '-1', '1.5']:
            with self.subTest(length=length):
                self.assertEqual(self.raw(f'Content-Length: {length}\r\n')[0], 400)
        self.assert_no_save()

    def test_missing_length_is_http_error(self):
        self.assertEqual(self.raw('')[0], 411)
        self.assert_no_save()

    def test_duplicate_length_is_http_error(self):
        self.assertEqual(self.raw('Content-Length: 0\r\nContent-Length: 1\r\n')[0], 400)
        self.assert_no_save()

    def test_oversized_length_is_http_error(self):
        self.assertEqual(self.raw(f'Content-Length: {(1 << 30) + 1}\r\n')[0], 413)
        self.assert_no_save()

    def test_transfer_encoding_is_rejected(self):
        self.assertEqual(self.raw('Transfer-Encoding: chunked\r\n', b'0\r\n\r\n')[0], 400)
        self.assert_no_save()

    def test_short_body_is_http_error(self):
        self.assertEqual(self.raw('Content-Length: 20\r\n', b'abc')[0], 400)
        self.assert_no_save()

    def test_filesystem_failure_is_http_error(self):
        (self.root / 'renders').write_text('occupied', encoding='utf-8')
        self.assertEqual(self.request(data_url(png()))[0], 500)
        self.assertEqual((self.root / 'renders').read_text(), 'occupied')

    def test_explicit_overwrite_replaces_only_a_valid_png(self):
        folder = self.root / 'renders'
        folder.mkdir()
        old = png(b'\x00\xff\x00\xff')
        target = folder / 'shot.png'
        target.write_bytes(old)
        path = '/save?name=shot.png&overwrite=1'
        self.assertEqual(self.request(data_url(b'bad'), path=path)[0], 400)
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(self.request(data_url(png()), path=path)[0], 200)
        self.assertEqual(target.read_bytes(), png())
        self.assertEqual(list(folder.iterdir()), [target])

    def test_concurrent_saves_publish_exactly_one_complete_file(self):
        images = [png(), png(b'\x00\xff\x00\xff')]
        barrier = threading.Barrier(2)
        def save(image):
            barrier.wait(timeout=3)
            return self.request(data_url(image))[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(save, images))
        self.assertEqual(sorted(statuses), [200, 409])
        target = self.root / 'renders' / 'shot.png'
        self.assertEqual(target.read_bytes(), images[statuses.index(200)])
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_invalid_options_never_fall_back_to_overwrite_or_basename(self):
        for query in ['name=../shot.png', 'name=a%5Cshot.png', 'name=C%3Ashot.png',
                      'name=con.png', 'name=shot.png&name=other.png',
                      'name=shot.png&overwrite=true', 'name=shot.png&overwrite=1&overwrite=0']:
            with self.subTest(query=query):
                self.assertEqual(self.request(data_url(png()), path='/save?' + query)[0], 400)
        self.assertFalse((self.root / 'renders').exists())

    def test_cross_origin_denoising_is_also_rejected(self):
        self.assertEqual(self.request(b'payload', path='/pt_denoise', headers={'Origin': 'null'})[0], 403)
        self.assertEqual(self.request(data_url(png()), headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assert_no_save()

    def test_localhost_origin_is_compatible(self):
        host = f'localhost:{self.port}'
        self.assertEqual(self.request(data_url(png()), headers={'Host': host, 'Origin': 'http://' + host})[0], 200)

    def test_valid_png_colour_depth_and_interlace_variants(self):
        # Independent one-pixel scanlines; even Adam7 has just its first pass for 1x1.
        for colour, depth, pixels in [(0, 1, b'\x80'), (2, 8, b'\xff\x00\x00'),
                                      (3, 1, b'\x00'), (4, 16, b'\xff\xff\xff\xff'),
                                      (6, 16, b'\xff\xff' * 4)]:
            for interlace in (0, 1):
                with self.subTest(colour=colour, depth=depth, interlace=interlace):
                    header = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, depth, colour, 0, 0, interlace))
                    palette = chunk(b'PLTE', b'\xff\x00\x00') if colour == 3 else b''
                    compressed = zlib.compress(b'\x00' + pixels)
                    image = (b'\x89PNG\r\n\x1a\n' + header + palette + chunk(b'tEXt', b'Note\x00test')
                             + chunk(b'IDAT', compressed[:3]) + chunk(b'IDAT', compressed[3:]) + chunk(b'IEND', b''))
                    path = f'/save?name=c{colour}-d{depth}-i{interlace}.png'
                    self.assertEqual(self.request(data_url(image), path=path)[0], 200)

    def test_invalid_image_data_with_correct_crcs_is_rejected(self):
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        for encoded in [b'not-zlib', zlib.compress(b'\x00'), zlib.compress(b'\x05\x00\x00\x00\xff'),
                        zlib.compress(b'\x00' * 6), zlib.compress(b'\x00' * 5)[:-1]]:
            with self.subTest(encoded=encoded):
                image = b'\x89PNG\r\n\x1a\n' + header + chunk(b'IDAT', encoded) + chunk(b'IEND', b'')
                self.assertEqual(self.request(data_url(image))[0], 400)
        self.assert_no_save()

    def test_extreme_png_dimensions_are_bounded_before_decompression(self):
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 100000, 100000, 8, 6, 0, 0, 0))
        image = b'\x89PNG\r\n\x1a\n' + header + chunk(b'IDAT', zlib.compress(b'')) + chunk(b'IEND', b'')
        self.assertEqual(self.request(data_url(image))[0], 413)
        self.assert_no_save()


class ServerFailureTests(unittest.TestCase):
    def setUp(self):
        # Importing the server must neither bind a port nor parse unittest's argv.
        with mock.patch.dict(sys.modules, {'ptdenoise': None}):
            self.server_module = runpy.run_path(str(ROOT / 'serve.py'))
        self.temp = tempfile.TemporaryDirectory(prefix='facade-http-failure-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_failed_publish_preserves_old_file_and_removes_staging_file(self):
        folder = self.root / 'renders'
        folder.mkdir()
        target = folder / 'shot.png'
        target.write_bytes(b'original')
        with mock.patch('os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.server_module['save_png'](str(self.root), 'shot.png', png(), overwrite=True)
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(list(folder.iterdir()), [target])

    def test_flush_failure_never_publishes_partial_file(self):
        with mock.patch('os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.server_module['save_png'](str(self.root), 'shot.png', png())
        self.assertEqual(list((self.root / 'renders').iterdir()), [])

    def start(self):
        server = self.server_module['create_server'](root=str(self.root), port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def stop():
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
        self.addCleanup(stop)
        return server.server_port

    def test_stalled_body_gets_timeout_response(self):
        self.server_module['Handler'].request_timeout = .1
        port = self.start()
        with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
            sock.sendall(f'POST /save HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 5\r\n\r\nx'.encode())
            response = http.client.HTTPResponse(sock)
            response.begin()
            self.assertEqual(response.status, 408)
            self.assertIn(b'timed out', response.read())
        self.assertFalse((self.root / 'renders').exists())

    def test_optional_backend_http_success_contract(self):
        # A counted fake backend checks dispatch/bytes/headers, not OIDN numerical quality.
        backend = mock.Mock()
        backend.process.return_value = (png(), {'pixels': 1})
        globals_ = self.server_module['Handler'].do_POST.__globals__
        with mock.patch.dict(globals_, {'PT_OK': True, 'PT_WHY': 'test backend', 'ptdenoise': backend}):
            port = self.start()
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            self.addCleanup(conn.close)
            conn.request('POST', '/pt_denoise', b'packed payload')
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'image/png')
            self.assertEqual(response.getheader('X-MOCKUP-PT-Denoise'), '1')
            self.assertEqual(json.loads(response.getheader('X-PT-Stats'))['pixels'], 1)
            self.assertEqual(response.read(), png())
            backend.process.assert_called_once_with(bytearray(b'packed payload'))


if __name__ == '__main__':
    unittest.main()
