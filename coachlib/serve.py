"""The page with working buttons: a small local server over one coach's page folder.

The page is a static file, and a file page can't run anything. `serve` puts the same page on
http://127.0.0.1:<port>/ and answers its buttons: each button POSTs to /api/<action>, the
coach's own function does the work (the same one its CLI command calls), and the page rebuilds
and reloads. Opened as a file instead, the page still works and each button copies its command.

Only this machine can reach it: it binds 127.0.0.1, answers only Host 127.0.0.1 / localhost
(so a web page can't reach it through DNS rebinding), and every POST needs the token the
server writes into the page it serves (so another site can't post to it). It stops itself
after `idle` seconds without a request; an open page pings it every minute.

Standard library only. Clips are served with byte ranges, so the video seeks as it does from a
file.
"""
from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

PORT = 8765
IDLE_S = 30 * 60
CHUNK = 1 << 20
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("audio/x-mpegurl", ".m3u")

# An action takes the button's JSON args and returns {"message": str, "reload": bool} (or raises
# ValueError / FileNotFoundError with a message for the player). A slow one goes through Jobs.
Action = Callable[[dict], dict]


class Jobs:
    """One background worker: slow actions (a GPU re-encode) queue here so a button returns at
    once. The page shows `status()`, can cancel a job that hasn't started, and the server stays
    up while anything is queued. A job is (key, label, fn): key de-duplicates, label is shown."""

    def __init__(self, on_done: Callable[[], None] | None = None):
        self.lock = threading.Lock()
        self.queue: list[tuple[str, str, Callable[[], str]]] = []
        self.current: tuple[str, str] | None = None
        self.log: list[str] = []
        self.on_done = on_done
        self.thread: threading.Thread | None = None

    def add(self, key: str, label: str, fn: Callable[[], str]) -> bool:
        """Queue a job; False if that key is already running or queued."""
        with self.lock:
            if (self.current and self.current[0] == key) or any(key == k for k, _, _ in self.queue):
                return False
            self.queue.append((key, label, fn))
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
            return True

    def cancel(self, key: str) -> bool:
        with self.lock:
            n = len(self.queue)
            self.queue = [q for q in self.queue if q[0] != key]
            return len(self.queue) < n

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    self.current = None
                    return
                key, label, fn = self.queue.pop(0)
                self.current = (key, label)
            try:
                msg = fn() or f"{label}: done"
            except Exception as e:          # a failed job is reported, never kills the server
                msg = f"{label}: failed ({e})"
                traceback.print_exc()
            print(f"serve: {msg}", flush=True)
            with self.lock:
                self.log = (self.log + [msg])[-20:]
            if self.on_done:
                try:
                    self.on_done()
                except Exception:
                    traceback.print_exc()

    def busy(self) -> bool:
        with self.lock:
            return bool(self.current or self.queue)

    def status(self) -> dict:
        with self.lock:
            return {"current": self.current[1] if self.current else None,
                    "current_key": self.current[0] if self.current else None,
                    "queued": [{"key": k, "label": l} for k, l, _ in self.queue], "log": list(self.log)}


def _api_tag(token: str) -> bytes:
    return f'<script>window.COACH_API={{token:{json.dumps(token)}}};</script>'.encode()


def make_handler(root: Path, page: str, actions: dict[str, Action], rebuild: Callable[[], None],
                 jobs: Jobs, token: str, port: int, seen: list[float], mounts: dict[str, Path] | None = None):
    root = root.resolve()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    # another coach's page folder at /<name>/; the pages link to each other with file: URLs,
    # which a browser won't follow from an http page, so served HTML gets them rewritten
    mounts = {k: Path(v).resolve() for k, v in (mounts or {}).items()}
    uris = sorted([(root.as_uri() + "/", "/")] + [(v.as_uri() + "/", f"/{k}/") for k, v in mounts.items()], key=lambda u: -len(u[0]))

    def local_links(html: bytes) -> bytes:
        for uri, to in uris:
            html = html.replace(uri.encode(), to.encode())
        return html

    class Handler(BaseHTTPRequestHandler):
        server_version = "coachclaude"

        def log_message(self, fmt, *args):      # quiet: one line per action, not per clip range
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj).encode())

        def _host_ok(self) -> bool:
            if self.headers.get("Host") in hosts:
                return True
            self._send(403, b"forbidden", "text/plain")
            return False

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            seen[0] = time.monotonic()
            if not self._host_ok():
                return
            path = unquote(urlsplit(self.path).path)
            if path == "/api/ping":
                return self._json(200, {"ok": True, "app": "coachclaude", "jobs": jobs.status()})
            if path in ("/", "/" + page):
                try:
                    html = (root / page).read_bytes()
                except OSError:
                    return self._send(404, b"no page yet: coach a match first", "text/plain")
                html = local_links(html).replace(b"</head>", _api_tag(token) + b"</head>", 1)
                return self._send(200, html, "text/html; charset=utf-8")
            self._file(path)

        def _file(self, path: str):
            base, rel = root, path.lstrip("/")
            head, _, rest = rel.partition("/")
            if head in mounts:
                base, rel = mounts[head], rest or page
            try:
                f = (base / rel).resolve()
                f.relative_to(base)
            except (ValueError, OSError):
                return self._send(404, b"not found", "text/plain")
            if not f.is_file():
                return self._send(404, b"not found", "text/plain")
            if f.suffix == ".html":
                return self._send(200, local_links(f.read_bytes()), "text/html; charset=utf-8")
            size = f.stat().st_size
            start, end, code = 0, size - 1, 200
            m = RANGE_RE.match(self.headers.get("Range") or "")
            if m and size:
                a, b = m.groups()
                if a:
                    start, end = int(a), min(int(b), size - 1) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                if start > end or start >= size:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                code = 206
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with f.open("rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        buf = fh.read(min(CHUNK, left))
                        if not buf:
                            break
                        self.wfile.write(buf)
                        left -= len(buf)
            except (ConnectionError, OSError):       # the browser drops a range it no longer wants
                pass

        def do_POST(self):
            seen[0] = time.monotonic()
            if not self._host_ok():
                return
            if not secrets.compare_digest(self.headers.get("X-Coach-Token") or "", token):
                return self._json(403, {"ok": False, "message": "this page is from an older server: reload it"})
            name = urlsplit(self.path).path.removeprefix("/api/")
            fn = actions.get(name)
            if name == "cancel":                    # every server can cancel a queued job
                fn = lambda a: {"message": "Cancelled." if jobs.cancel(str(a.get("key"))) else "That one has already started or finished."}
            if fn is None:
                return self._json(404, {"ok": False, "message": f"no action {name!r}"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                args = json.loads(self.rfile.read(n) or b"{}") if n else {}
                res = fn(args if isinstance(args, dict) else {}) or {}
            except (ValueError, FileNotFoundError) as e:
                return self._json(400, {"ok": False, "message": str(e)})
            except Exception as e:
                traceback.print_exc()
                return self._json(500, {"ok": False, "message": f"{type(e).__name__}: {e}"})
            print(f"serve: {name} {json.dumps(args)} -> {res.get('message', 'ok')}", flush=True)
            if res.get("reload"):
                try:
                    rebuild()
                except Exception:
                    traceback.print_exc()
            self._json(200, {"ok": True, **res})

    return Handler


def running(port: int = PORT) -> bool:
    """A coachclaude server already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "coachclaude"
    except (OSError, ValueError):
        return False


def serve(root: Path, page: str, actions: dict[str, Action], rebuild: Callable[[], None],
          jobs: Jobs | None = None, port: int = PORT, open_browser: bool = True, idle: float = IDLE_S,
          mounts: dict[str, Path] | None = None) -> None:
    """Serve `root` (page at /, and each of `mounts` at /<name>/) until `idle` seconds pass with
    no request and no job running. If a coachclaude server already has the port, just open the
    page there."""
    url = f"http://127.0.0.1:{port}/"
    if running(port):
        print(f"serve: already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return
    jobs = jobs or Jobs()
    seen = [time.monotonic()]
    token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Path(root), page, actions, rebuild, jobs, token, port, seen, mounts))
    httpd.daemon_threads = True

    def watchdog():
        while True:
            time.sleep(15)
            if jobs.busy():
                seen[0] = time.monotonic()
            elif time.monotonic() - seen[0] > idle:
                print(f"serve: idle for {idle / 60:.0f} min, stopping", flush=True)
                httpd.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    print(f"serve: {url} (Ctrl+C stops it; it also stops after {idle / 60:.0f} idle minutes)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
