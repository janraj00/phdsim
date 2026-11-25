"""Serve the local viewer and one selected mission export on loopback."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
DEFAULT_MISSION = APP.parents[1] / "runs/scout-visualizer-demo/mission.json"
DEFAULT_SEMANTIC = APP.parents[1] / "runs/scout-semantic-demo/mission.json"
ASSETS = {"index.html", "viewer.css", "viewer.mjs", "map.mjs", "replay.mjs", "semantic.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    parser.add_argument("--semantic", type=Path, default=DEFAULT_SEMANTIC)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript"}

        def send_head(self):
            path = urlsplit(self.path).path
            if path not in {"/", "/mission.json"} and path[1:] not in ASSETS:
                self.send_error(404)
                return None
            return super().send_head()

        def translate_path(self, path):
            name = urlsplit(path).path.lstrip("/") or "index.html"
            selected = {"mission.json": args.mission, "semantic.json": args.semantic}
            return str(selected[name].resolve() if name in selected else APP / name)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"SCOUT viewer  http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
