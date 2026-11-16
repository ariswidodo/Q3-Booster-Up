# -*- coding: utf-8 -*-
"""Server lokal mandiri untuk Q3 Booster Up Dashboard (port 8766)."""
import argparse
import json
import mimetypes
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
INBOX_DIR = os.path.join(ROOT, "inbox")
os.makedirs(INBOX_DIR, exist_ok=True)
sys.path.insert(0, SCRIPTS_DIR)

import booster_engine as BE

LOCK = threading.Lock()
JOB = {"running": False, "done": False, "error": "", "logs": [], "stats": None}


def _emit(msg):
    with LOCK:
        JOB["logs"].append(msg)


def _run_upload(dst):
    try:
        stats = BE.process_sellout_xlsx(dst, ROOT, emit=_emit)
        with LOCK:
            JOB["stats"] = stats
            JOB["done"] = True
            JOB["running"] = False
    except Exception as exc:
        _emit(f"ERROR: {exc}")
        with LOCK:
            JOB["error"] = str(exc)
            JOB["done"] = True
            JOB["running"] = False


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            with LOCK:
                return self._send_json(dict(JOB))

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        safe = os.path.normpath(os.path.join(ROOT, urllib.parse.unquote(rel)))
        if not safe.startswith(ROOT) or not os.path.isfile(safe):
            self.send_error(404)
            return

        ctype, _ = mimetypes.guess_type(safe)
        with open(safe, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        if safe.endswith((".html", ".css", ".js", ".json")):
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/program-rules":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                start = (body.get("start") or "").strip()
                end = (body.get("end") or "").strip()
                rpath = os.path.join(ROOT, "data", "program_rules.json")
                with open(rpath, encoding="utf-8") as rf:
                    rules = json.load(rf)
                if "Q3 Booster Up" in rules:
                    rules["Q3 Booster Up"]["start"] = start
                    rules["Q3 Booster Up"]["end"] = end
                with open(rpath, "w", encoding="utf-8") as wf:
                    json.dump(rules, wf, ensure_ascii=False, indent=2)
                BE.export_booster_json(ROOT)
                return self._send_json({"ok": True, "rule": rules.get("Q3 Booster Up", {})})
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)}, 500)

        if parsed.path == "/api/update-master":
            kind = (self.headers.get("X-Master-Kind") or "").strip().lower()
            try:
                if kind == "refresh":
                    st = BE.export_booster_json(ROOT)
                    return self._send_json({"ok": True, "message": "Data Q3 Booster Up berhasil di-refresh.", **st})
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return self._send_json({"ok": False, "error": "File kosong."}, 400)
                fname = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "master.xlsx"))) or "master.xlsx"
                dst = os.path.join(INBOX_DIR, f"master_{kind}_{fname}")
                with open(dst, "wb") as f:
                    f.write(self.rfile.read(length))
                if kind == "participants":
                    return self._send_json({"ok": True, **BE.sync_participants(dst, ROOT)})
                if kind == "skus":
                    return self._send_json({"ok": True, **BE.sync_skus(dst, ROOT)})
                return self._send_json({"ok": False, "error": f"Jenis master tidak dikenal: {kind}"}, 400)
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)}, 500)

        if parsed.path != "/api/upload":
            self.send_error(404)
            return

        with LOCK:
            if JOB["running"]:
                return self._send_json({"ok": False, "error": "Proses upload sedang berjalan."}, 409)

        fname = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "sellout.xlsx"))) or "sellout.xlsx"
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._send_json({"ok": False, "error": "File kosong."}, 400)
        data = self.rfile.read(length)
        dst = os.path.join(INBOX_DIR, fname)
        with open(dst, "wb") as f:
            f.write(data)

        with LOCK:
            JOB["running"] = True
            JOB["done"] = False
            JOB["error"] = ""
            JOB["logs"] = [f"Menerima file: {fname} ({len(data)/1024/1024:.2f} MB)"]
            JOB["stats"] = None

        threading.Thread(target=_run_upload, args=(dst,), daemon=True).start()
        return self._send_json({"ok": True})


def _setup_headless_streams():
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(ROOT, "data", "server.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_f = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log_f
    if sys.stderr is None:
        sys.stderr = log_f


def _is_port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def main():
    _setup_headless_streams()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}/"
    if _is_port_open(args.port):
        print(f"Q3 Booster Up Dashboard sudah berjalan di {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Q3 Booster Up Dashboard berjalan di {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDihentikan.")


if __name__ == "__main__":
    main()
