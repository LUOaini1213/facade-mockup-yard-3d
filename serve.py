# Local server for the VMU site viewer.
#   python serve.py [port]      (default port 18090 -> http://127.0.0.1:18090/index.html)
#   static files (read-only) from this folder
#   POST /save?name=xxx.png   PNG data URL -> renders/xxx.png (409 if present; overwrite=1 opts in)
#   POST /pt_denoise          path-traced still: float accumulation + AOVs (viewer.js ptFinalize) -> denoised PNG
#                             (Intel Open Image Denoise, fog, ACES, sRGB; ptdenoise.py). 501 when numpy or the DLL is missing,
#                             the viewer then falls back to its in-browser DenoiseMaterial (or raw).
#   GET  /pt_denoise          {"available": bool, "reason": str}
# Every response carries X-MOCKUP-Serve (this server) and X-MOCKUP-PT-Denoise ('1' or '0; reason'); the viewer reads them from
# one GET of index.html, so on a plain static host it never POSTs (no failed requests, no console errors).
import http.server, os, sys, base64, urllib.parse, functools, json, time, traceback
import binascii, re, socket, struct, tempfile, zlib

sys.dont_write_bytecode = True   # no __pycache__ next to the viewer
ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 1 << 30
MAX_SAVE_BODY = 64 << 20
MAX_PNG_RAW = 256 << 20

try:
    sys.path.insert(0, ROOT)
    import ptdenoise
    PT_OK, PT_WHY = ptdenoise.available()
except Exception as e:  # numpy / ctypes import problems must never stop the static server
    ptdenoise, PT_OK, PT_WHY = None, False, f'ptdenoise import failed ({type(e).__name__}: {e})'


def _latin1(s):
    return str(s).replace('\r', ' ').replace('\n', ' ').encode('ascii', 'replace').decode('ascii')[:160]


class RequestError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def png_data(body):
    """Validate a screenshot's PNG framing, CRCs and bounded image data, without Pillow.

    Ancillary metadata is retained; it is not interpreted. Both PNG interlace modes
    and the standard colour types/bit depths are accepted.
    """
    prefix = b'data:image/png;base64,'
    if not body.startswith(prefix):
        raise ValueError('expected a PNG data URL')
    data = base64.b64decode(body[len(prefix):], validate=True)
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('invalid PNG signature')
    pos, ihdr, palette, ended, idat_closed = 8, None, False, False, False
    compressed = bytearray()
    saw_idat = False
    while pos < len(data):
        if len(data) - pos < 12:
            raise ValueError('truncated PNG chunk')
        size, kind = struct.unpack_from('>I4s', data, pos)
        end = pos + 12 + size
        if end > len(data) or not re.fullmatch(b'[A-Za-z]{4}', kind) or kind[2] & 32:
            raise ValueError('invalid PNG chunk')
        payload = data[pos + 8:end - 4]
        if zlib.crc32(kind + payload) != struct.unpack_from('>I', data, end - 4)[0]:
            raise ValueError('invalid PNG CRC')
        if ihdr is None and kind != b'IHDR':
            raise ValueError('PNG must start with IHDR')
        if kind == b'IHDR':
            if ihdr is not None or size != 13:
                raise ValueError('invalid PNG header')
            ihdr = struct.unpack('>IIBBBBB', payload)
            w, h, depth, colour, compression, filtering, interlace = ihdr
            depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not 0 < w < 2**31 or not 0 < h < 2**31 or depth not in depths.get(colour, ())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise ValueError('unsupported PNG header')
        elif kind == b'PLTE':
            if palette or saw_idat or colour in (0, 4) or not size or size % 3 or size > 768:
                raise ValueError('invalid PNG palette')
            if colour == 3 and size // 3 > 2**depth:
                raise ValueError('PNG palette exceeds bit depth')
            palette = True
        elif kind == b'IDAT':
            if idat_closed or (colour == 3 and not palette):
                raise ValueError('invalid PNG image chunk order')
            saw_idat = True
            compressed.extend(payload)
        elif kind == b'IEND':
            if size or not saw_idat or end != len(data):
                raise ValueError('invalid PNG end')
            ended = True
        elif not kind[0] & 32:
            raise ValueError('unknown critical PNG chunk')
        if saw_idat and kind != b'IDAT':
            idat_closed = True
        pos = end
    if not ended:
        raise ValueError('missing PNG end')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    passes = [(0, 0, 1, 1)] if not interlace else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    rows = []
    for x, y, dx, dy in passes:
        pw, ph = max(0, (w - x + dx - 1) // dx), max(0, (h - y + dy - 1) // dy)
        if pw and ph:
            rows.append((1 + (pw * channels * depth + 7) // 8, ph))
    expected = sum(stride * count for stride, count in rows)
    if expected > MAX_PNG_RAW:
        raise RequestError(413, 'PNG image data is too large')
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected + 1)
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid PNG image data length or compression')
    offset = 0
    for stride, count in rows:
        if any(raw[offset + row * stride] > 4 for row in range(count)):
            raise ValueError('invalid PNG scanline filter')
        offset += stride * count
    return data


def save_png(root, name, data, overwrite=False):
    """Publish a complete file atomically; a concurrent default save cannot clobber it."""
    folder = os.path.join(root, 'renders')
    os.makedirs(folder, exist_ok=True)
    if os.path.realpath(folder) != os.path.join(os.path.realpath(root), 'renders'):
        raise OSError('renders must be a directory inside the viewer root')
    target = os.path.join(folder, name)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.save-', suffix='.tmp', delete=False) as f:
            temporary = f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            # Unlike a check followed by replace(), link() is an atomic no-clobber publish.
            try:
                os.link(temporary, target)
            except FileExistsError:
                raise RequestError(409, 'render already exists; use overwrite=1 to replace it') from None
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript', '.glb': 'model/gltf-binary', '.json': 'application/json'}

    def end_headers(self):
        self.send_header('X-MOCKUP-Serve', '2')
        self.send_header('X-MOCKUP-PT-Denoise', '1' if PT_OK else '0; ' + _latin1(PT_WHY))
        super().end_headers()

    request_timeout = 30

    def setup(self):
        self.request.settimeout(self.request_timeout)
        super().setup()

    def _local_post(self):
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.server.server_port == 80:
            allowed.update(('127.0.0.1', 'localhost'))
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            raise RequestError(403, 'POST requires this local server Host')
        if origins and (len(origins) != 1 or origins[0].lower() != 'http://' + hosts[0].lower()):
            raise RequestError(403, 'cross-origin POST is not allowed')
        if self.headers.get('Sec-Fetch-Site', '').lower() in ('cross-site', 'same-site'):
            raise RequestError(403, 'cross-origin POST is not allowed')

    def _body(self, limit=MAX_BODY):
        if self.headers.get_all('Transfer-Encoding'):
            raise RequestError(400, 'Transfer-Encoding is not supported')
        lengths = self.headers.get_all('Content-Length', [])
        if not lengths:
            raise RequestError(411, 'Content-Length is required')
        if len(lengths) != 1 or not re.fullmatch('[0-9]+', lengths[0]):
            raise RequestError(400, 'invalid Content-Length')
        n = int(lengths[0])
        if n > limit:
            raise RequestError(413, 'request body is too large')
        body = bytearray(n); mv = memoryview(body); got = 0
        while got < n:   # chunked: one large read can fail under memory pressure
            k = self.rfile.readinto(mv[got:got + (8 << 20)])
            if not k:
                raise RequestError(400, f'short body {got}/{n}')
            got += k
        return body

    def _json(self, code, obj):
        b = json.dumps(obj).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == '/pt_denoise':
            return self._json(200, {'available': PT_OK, 'reason': PT_WHY})
        return super().do_GET()

    def do_POST(self):
        try:
            self._local_post()
            return self._post()
        except RequestError as e:
            return self._json(e.code, {'error': str(e)})
        except (ValueError, binascii.Error, zlib.error) as e:
            return self._json(400, {'error': _latin1(e)})
        except socket.timeout:
            return self._json(408, {'error': 'request body timed out'})
        except OSError:
            return self._json(500, {'error': 'could not save the render'})

    def _post(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/save':
            query = urllib.parse.parse_qs(u.query, keep_blank_values=True)
            names, overwrite = query.get('name', ['shot.png']), query.get('overwrite', ['0'])
            if len(names) != 1 or overwrite not in (['0'], ['1']):
                raise ValueError('invalid save options')
            name = names[0]
            if (not name.lower().endswith('.png') or re.search(r'[\x00-\x1f<>:"/\\|?*]', name)
                    or name.startswith('.') or name[-1:] in (' ', '.')
                    or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])\..*', name)):
                raise ValueError('name must be a plain PNG filename')
            data = png_data(bytes(self._body(MAX_SAVE_BODY)))
            save_png(self.directory, name, data, overwrite == ['1'])
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', '2')
            self.end_headers(); self.wfile.write(b'ok')
        elif u.path == '/pt_denoise':
            body = self._body()
            if not PT_OK:
                return self._json(501, {'error': 'pt_denoise unavailable', 'reason': PT_WHY})
            try:
                t0 = time.time()
                png, st = ptdenoise.process(body)
                st['server_s'] = round(time.time() - t0, 3)
            except Exception as e:
                traceback.print_exc()
                return self._json(500, {'error': _latin1(f'{type(e).__name__}: {e}')})
            self.send_response(200)
            self.send_header('Content-Type', 'image/png'); self.send_header('Content-Length', str(len(png)))
            js = json.dumps(st, ensure_ascii=True)
            self.send_header('X-PT-Stats', js if len(js) < 8000 else '{}')
            self.end_headers(); self.wfile.write(png)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def create_server(root=ROOT, port=18090):
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(Handler, directory=os.path.abspath(root)))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18090
    with create_server(port=port) as httpd:
        print(f'VMU site viewer: http://127.0.0.1:{httpd.server_port}/index.html  (pt_denoise: {"OIDN" if PT_OK else "off - " + PT_WHY})', flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    main()
