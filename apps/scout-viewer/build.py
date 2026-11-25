"""Package SCOUT Viewer and selected replay data into one offline HTML file."""

from argparse import ArgumentParser
import json
from pathlib import Path
import re

from serve import APP, DEFAULT_MISSION, DEFAULT_SEMANTIC


def build(output: Path, mission: Path, semantic: Path) -> None:
    demo = {}
    for key, path in (("mission.json", mission), ("semantic.json", semantic)):
        if path.is_file():
            demo[key] = json.loads(path.read_text(encoding="utf-8"))
    if not demo:
        raise ValueError("Generate a mission replay or specify an existing JSON file")
    data = json.dumps(demo, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    sources = []
    for name in ("replay.mjs", "map.mjs", "viewer.mjs"):
        source = (APP / name).read_text(encoding="utf-8")
        source = re.sub(r"^import [^\n]+\n", "", source, flags=re.MULTILINE)
        sources.append(re.sub(r"^export (?=(function|const) )", "", source, flags=re.MULTILINE))
    script = "\n".join(sources)
    css = (APP / "viewer.css").read_text(encoding="utf-8")
    page = (APP / "index.html").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="./viewer.css">', f"<style>\n{css}\n</style>")
    page = page.replace('<script type="module" src="./viewer.mjs"></script>',
                        f'<script id="scout-bundled-replays" type="application/json">{data}</script>\n'
                        f'<script type="module">\n{script}\n</script>')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as fp:
        fp.write(page)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    parser.add_argument("--semantic", type=Path, default=DEFAULT_SEMANTIC)
    args = parser.parse_args()
    try:
        build(args.output, args.mission, args.semantic)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
