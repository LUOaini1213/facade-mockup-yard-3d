"""Capture all final public viewer cameras without modifying the web app or GLBs."""
import functools
import http.server
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--use-angle=swiftshader'])
            page = browser.new_page(viewport={'width': 1600, 'height': 1000})
            page.goto(f'http://127.0.0.1:{server.server_port}/index.html', wait_until='domcontentloaded')
            page.wait_for_function('window.__loadReport && Object.keys(window.__v.VIEWS).length === 13', timeout=180000)
            result = page.evaluate('''() => ({source: "viewer.js final VIEWS runtime", frame: "glTF metres, Y up",
                fov_y_degrees: __v.camera.fov, width:1600, height:1000,
                near_m:__v.camera.near, far_m:__v.camera.far,
                views:Object.entries(__v.VIEWS).map(([key,v]) => ({key,name:v.name,
                    position:v.pos.toArray(),target:v.target.toArray(),up:__v.camera.up.toArray()}))})''')
            (ROOT / 'model' / 'rhino_views.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            browser.close()
            print('Captured', len(result['views']), 'exact public viewer cameras')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
