"""Bundle SCOUT Mission Studio and selected replay JSONs into a single offline HTML file."""
from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import re

from serve import APP, RUNS_DIR

DEFAULT_BUNDLES = [
    ("scout-semantic-x500/mission.json", RUNS_DIR / "scout-semantic-x500/mission.json"),
    ("scout-semantic-x500-fixed/mission.json", RUNS_DIR / "scout-semantic-x500-fixed/mission.json"),
    ("scout-visualizer-demo/mission.json", RUNS_DIR / "scout-visualizer-demo/mission.json"),
    ("scout-map/map.json", RUNS_DIR / "scout-map/map.json"),
]


def build(output: Path, missions: list[Path]) -> None:
    bundled: dict[str, dict] = {}
    if missions:
        for path in missions:
            if not path.is_file():
                raise ValueError(f"Mission file not found: {path}")
            key = f"{path.parent.name}/{path.name}"
            bundled[key] = json.loads(path.read_text(encoding="utf-8"))
    else:
        for key, path in DEFAULT_BUNDLES:
            if path.is_file():
                bundled[key] = json.loads(path.read_text(encoding="utf-8"))
    if not bundled:
        raise ValueError("No scout-replay-v1 JSON files found to bundle.")

    data_json = json.dumps(bundled, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    modules = []
    for name in ("replay.mjs", "analytics.mjs", "render2d.mjs", "render3d.mjs", "studio.mjs"):
        src = (APP / name).read_text(encoding="utf-8")
        src = re.sub(r"^import [\s\S]*?from ['\"]\.\/[^'\"]+['\"];\n", "", src, flags=re.MULTILINE)
        src = re.sub(r"^export (?=(function|const|class) )", "", src, flags=re.MULTILINE)
        modules.append(f"// --- {name} ---\n{src}")
    script = "\n".join(modules)
    css = (APP / "studio.css").read_text(encoding="utf-8")
    page = (APP / "index.html").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="./studio.css">', f"<style>\n{css}\n</style>")
    page = page.replace(
        '<script type="module" src="./studio.mjs"></script>',
        f'<script id="scout-studio-bundle" type="application/json">{data_json}</script>\n'
        f'<script type="module">\n{script}\n</script>',
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as fp:
        fp.write(page)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mission", type=Path, action="append", default=[], help="Mission JSON(s) to bundle")
    args = parser.parse_args()
    try:
        build(args.output, args.mission)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
