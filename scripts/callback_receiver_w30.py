#!/usr/bin/env python3
"""Isolated lab receipt collector. Accepts one fixed synthetic marker, never executes commands."""
import json
import re
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = Path(sys.argv[1])


class Receiver(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/receipts":
            self.send_error(404)
            return
        data = LOG.read_bytes() if LOG.exists() else b""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/receipt":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("size")
            body = json.loads(self.rfile.read(size))
            if set(body) != {"experiment", "case", "marker"} or body["experiment"] != "w30" or body["marker"] != "SYNTHETIC-STATUS-ONLY" or not re.fullmatch(r"w30-[a-z0-9-]{1,100}", body["case"]):
                raise ValueError("unexpected payload")
        except Exception:
            self.send_error(400)
            return
        event = {"received_utc": datetime.now(timezone.utc).isoformat(), "peer": self.client_address[0], "payload": body}
        with LOG.open("a") as f:
            f.write(json.dumps(event) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": True, "case": body["case"]}).encode())


class Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


if __name__ == "__main__":
    Server(("fd00:200::2", 18765), Receiver).serve_forever()
