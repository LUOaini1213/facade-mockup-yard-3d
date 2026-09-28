# Local server for the VMU site viewer.
#   python serve.py [port]      (default port 18090 -> http://127.0.0.1:18090/index.html)
#   static files (read-only) from this folder
#   POST /save?name=xxx.png   PNG data URL -> renders/xxx.png
#   POST /pt_denoise          path-traced still: float accumulation + AOVs (viewer.js ptFinalize) -> denoised PNG
#                             (Intel Open Image Denoise, fog, ACES, sRGB; ptdenoise.py). 501 when numpy or the DLL is missing,
#                             the viewer then falls back to its in-browser DenoiseMaterial (or raw).
#   GET  /pt_denoise          {"available": bool, "reason": str}
# Every response carries X-MOCKUP-Serve (this server) and X-MOCKUP-PT-Denoise ('1' or '0; reason'); the viewer reads them from
# one GET of index.html, so on a plain static host it never POSTs (no failed requests, no console errors).
import http.server, socketserver, os, sys, base64, urllib.parse, functools, json, time, traceback

sys.dont_write_bytecode = True   # no __pycache__ next to the viewer
ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18090
MAX_BODY = 1 << 30

try:
    sys.path.insert(0, ROOT)
    import ptdenoise
    PT_OK, PT_WHY = ptdenoise.available()
except Exception as e:  # numpy / ctypes import problems must never stop the static server
    ptdenoise, PT_OK, PT_WHY = None, False, f'ptdenoise import failed ({type(e).__name__}: {e})'


def _latin1(s):
    return str(s).encode('ascii', 'replace').decode('ascii')[:160]


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript', '.glb': 'model/gltf-binary', '.json': 'application/json'}

    def end_headers(self):
        self.send_header('X-MOCKUP-Serve', '2')
        self.send_header('X-MOCKUP-PT-Denoise', '1' if PT_OK else '0; ' + _latin1(PT_WHY))
        super().end_headers()

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        if n < 0 or n > MAX_BODY:
            raise ValueError(f'body size {n}')
        body = bytearray(n); mv = memoryview(body); got = 0
        while got < n:   # chunked: one large read can fail under memory pressure
            k = self.rfile.readinto(mv[got:got + (8 << 20)])
            if not k:
                raise IOError(f'short body {got}/{n}')
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
        u = urllib.parse.urlparse(self.path)
        if u.path == '/save':
            name = os.path.basename(urllib.parse.parse_qs(u.query).get('name', ['shot.png'])[0])
            if not name.lower().endswith('.png'):
                self.send_error(400); return
            body = bytes(self._body()).decode('ascii')
            data = base64.b64decode(body.split(',', 1)[-1])
            os.makedirs(os.path.join(ROOT, 'renders'), exist_ok=True)
            with open(os.path.join(ROOT, 'renders', name), 'wb') as f:
                f.write(data)
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        elif u.path == '/pt_denoise':
            try:
                body = self._body()   # always drain the request
            except Exception as e:
                return self._json(400, {'error': _latin1(e)})
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


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(('127.0.0.1', PORT), functools.partial(Handler, directory=ROOT)) as httpd:
    print(f'VMU site viewer: http://127.0.0.1:{PORT}/index.html  (pt_denoise: {"OIDN" if PT_OK else "off - " + PT_WHY})', flush=True)
    httpd.serve_forever()
