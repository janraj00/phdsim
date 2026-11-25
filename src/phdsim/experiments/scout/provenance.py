"""Fingerprint every implementation module participating in the SCOUT pilot."""

import hashlib
from pathlib import Path
import subprocess


def source_identity(extra_sources=()):
    root = Path(__file__).resolve().parents[4]
    package = root/"src/phdsim"
    folders = ("agents", "belief", "communication", "environments", "planning",
               "sensors", "simulation", "decision/acquisition", "experiments/scout", "scout")
    sources = {p for name in folders for p in (package/name).rglob("*.py")}
    sources.update(package/p for p in ("core/grid.py", "core/randomness.py",
                   "costs/mission.py", "evaluation/mission.py", "cli/scout.py", "cli/__init__.py"))
    sources.update(package/p for p in extra_sources)
    # Package initializers execute on import too; include them without importing
    # unrelated model stacks to discover the source tree.
    for source in tuple(sources):
        for folder in source.parents:
            if folder == package.parent:
                break
            initializer = folder/"__init__.py"
            if initializer.is_file():
                sources.add(initializer)
    digest = hashlib.sha256()
    paths = []
    for source in sorted(sources):
        relative = source.relative_to(root).as_posix()
        paths.append(relative)
        digest.update(relative.encode()+b"\0"+source.read_bytes())
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git = None
    return {"git_head": git, "scout_source_sha256": digest.hexdigest(), "source_files": paths}
