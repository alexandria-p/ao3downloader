"""A stand-in for GitHub's releases, so the Windows or Mac app can be updated end to end on a
build runner without publishing anything.

    python stand_in_release.py <the app's zip> <port> [version]

It answers `/repos/<anything>/releases/latest` as GitHub's api does - a newer version, with
the zip as an asset of the zip's own name (`ao3downloader-windows.zip`,
`ao3downloader-macos-intel.zip`...) and its real SHA-256 - and serves the zip.
The app is pointed at it with `AO3DOWNLOADER_UPDATE_SOURCE=http://127.0.0.1:<port>`
(`source_code/updater.py`). `build-windows.yml` and `build-mac.yml` use it to install the app, update it, and
check what the update changed and what it left alone.
"""

import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(archive: Path, port: int, version: str = '99.0.0') -> None:
    data = archive.read_bytes()
    # named as the release asset the app looks for, which is the name its zip is built with
    name = archive.name
    release = json.dumps({
        'tag_name': f'v{version}',
        'html_url': f'http://127.0.0.1:{port}/release',
        'assets': [{'name': name,
                    'browser_download_url': f'http://127.0.0.1:{port}/{name}',
                    'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
                    'size': len(data)}],
    }).encode('utf-8')

    class Answer(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith('/releases/latest'):
                body, kind = release, 'application/json'
            elif self.path == f'/{name}':
                body, kind = data, 'application/zip'
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args) -> None:
            print(f'stand-in release: {format % args}', flush=True)

    print(f'stand-in release {version} on http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Answer).serve_forever()


if __name__ == '__main__':
    serve(Path(sys.argv[1]), int(sys.argv[2]), *(sys.argv[3:4]))
