# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Tiny webhook receiver for manual verification of registry change broadcasts.

Example:
    python bin/webhook_receiver.py --port 15999 --secret whsec-demo

Every received batch is printed with a signature verdict and an event summary.
"""

import argparse
import hashlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description="Registry webhook receiver for manual verification")
    parser.add_argument("--port", type=int, default=15999)
    parser.add_argument("--secret", default="", help="HMAC secret used to verify X-Registry-Signature")
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            verdict = "unsigned (no secret configured)"
            if args.secret:
                timestamp = self.headers.get("X-Registry-Timestamp", "")
                signature = self.headers.get("X-Registry-Signature", "")
                expected = "sha256=" + hmac.new(
                    args.secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body,
                    hashlib.sha256).hexdigest()
                verdict = ("signature-valid"
                           if hmac.compare_digest(signature, expected) else "signature-INVALID")
            try:
                payload = json.loads(body.decode("utf-8"))
                events = payload.get("events", [])
                summary = ", ".join(
                    f"{e.get('event_type')}@v{e.get('registry_version')}:{e.get('data', {}).get('name')}"
                    for e in events)
            except (json.JSONDecodeError, UnicodeDecodeError):
                summary = "<unparseable body>"
            print(f"[ts={self.headers.get('X-Registry-Timestamp')}] {verdict} "
                  f"batch({len(events) if isinstance(events, list) else '?'}): {summary}", flush=True)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    print(f"Webhook receiver listening on 127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
