#!/usr/bin/env python3
"""Read-only HTTP repository. No HDC, credentials, or installation endpoints."""
import argparse
import functools
import http.server

class StaticRepository(http.server.SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.zip':'application/zip', '.gz':'application/gzip', '.hap':'application/zip'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--port', type=int, default=18090)
    args = parser.parse_args()
    handler = functools.partial(StaticRepository, directory=args.directory)
    print(f'Static download-only repository: http://127.0.0.1:{args.port}', flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1',args.port),handler).serve_forever()
