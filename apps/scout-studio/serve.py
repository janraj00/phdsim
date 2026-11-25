"""Serve SCOUT Mission Studio locally with automatic discovery of runs/ replays."""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

APP = Path(__file__).resolve().parent
REPO_ROOT = APP.parents[1]
RUNS_DIR = REPO_ROOT / "runs"
STATIC_ASSETS = {
    "index.html",
    "studio.css",
    "studio.mjs",
    "replay.mjs",
    "render2d.mjs",
    "render3d.mjs",
    "analytics.mjs",
}


def discover_missions(runs_dir: Path) -> list[dict]:
    """Find all scout-replay-v1 JSON files under runs_dir, sorted newest/richest first."""
    found: list[dict] = []
    if not runs_dir.is_dir():
        return found
    for path in sorted(runs_dir.rglob("*.json")):
        if path.stat().st_size > 25 * 1024 * 1024:
            continue
        try:
            with path.open("r", encoding="utf-8") as fp:
                head = fp.read(512)
                if '"scout-replay-v1"' not in head:
                    continue
                fp.seek(0)
                data = json.load(fp)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if data.get("schema") != "scout-replay-v1":
            continue
        rel = path.relative_to(runs_dir).as_posix()
        frames = data.get("frames") or []
        agents = data.get("agents") or []
        has_alt = any(
            "altitude_m" in a
            for f in frames[:5]
            for a in (f.get("agents") or [])
        )
        priority = (
            2 if "x500" in rel and rel.endswith("mission.json") else
            1 if rel.endswith("mission.json") else
            0
        )
        found.append({
            "id": rel,
            "path": path,
            "title": data.get("title", rel),
            "group": path.parent.name,
            "frames": len(frames),
            "agents": len(agents),
            "has_altitude": has_alt,
            "grid": data.get("grid"),
            "mtime": path.stat().st_mtime,
            "priority": priority,
        })
    found.sort(key=lambda item: (-item["priority"], -item["mtime"], item["id"]))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=RUNS_DIR, help="Directory scanned for scout-replay-v1 JSON files")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()

    runs_dir = args.runs.resolve()

    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript; charset=utf-8"}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path == "/api/missions":
                missions = discover_missions(runs_dir)
                payload = [
                    {k: v for k, v in m.items() if k not in {"path", "mtime", "priority"}}
                    for m in missions
                ]
                self._send_json(payload)
                return
            if parsed.path == "/api/mission":
                params = parse_qs(parsed.query)
                rel = (params.get("id") or [""])[0]
                missions = {m["id"]: m["path"] for m in discover_missions(runs_dir)}
                target = missions.get(rel)
                if not target or not target.is_file():
                    self.send_error(404, "Mission not found")
                    return
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def _send_json(self, obj: object) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_head(self):
            path = urlsplit(self.path).path
            name = path.lstrip("/") or "index.html"
            if name not in STATIC_ASSETS:
                self.send_error(404)
                return None
            return super().send_head()

        def translate_path(self, path: str) -> str:
            name = urlsplit(path).path.lstrip("/") or "index.html"
            return str((APP / name).resolve())

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"SCOUT Studio  http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
