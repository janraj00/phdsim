# Moving PHDSIM to another computer

The repository contains the research code, tests, configuration examples,
documentation and attributed third-party source references. Git does not contain
datasets, trained model weights, environment installations or generated outputs.
The inventory below was checked on **2026-10-19**.

## 1. Clone and recreate the Python environment

Authenticate GitHub CLI with the account that owns the private repository, then
clone it into any suitable local working directory:

```powershell
gh auth login
gh repo clone janraj00/phdsim
Set-Location phdsim
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[pstnet-training,urbaning]"
.\scripts\test.ps1
```

Tests use temporary fixtures and do not require the research datasets or saved
model checkpoints. No research training starts during setup. The source machine
passed 70 tests before the GitHub handoff. The full environment includes both
PSTNet and UrbanIng optional dependencies. For data inspection alone, installing
`.[urbaning]` is sufficient; the full test launcher additionally requires the
neural dependencies.

Do not copy `.venv` or `node_modules`; reinstall dependencies on the new machine.
The recorded source stack was Python 3.12.14, NumPy 2.3.5, Pillow 12.3.0,
PyTorch 2.14.1+cpu, torchvision 0.29.1+cpu, OpenCV 4.13.0.92, Matplotlib 3.11.2,
DuckDB 1.5.6 and py7zr 1.1.4. These are observed versions, not a cross-platform
lockfile. GPU environments need a suitable PyTorch/CUDA installation.

### Continue the research conversation

Open the cloned project in Codex. The root `AGENTS.md` points to
[the research handoff](CONTEXT.md), which records the latest decisions and verified
state. The [conversation archive](CHAT_HISTORY_2026-10-19.md) retains the recorded
user/assistant text for historical reference. It is a Markdown export, not a
restoration of the original chat as a native resumable app session. Binary
attachments, tool logs and internal application state are not embedded.

Start with: "Read AGENTS.md and docs/CONTEXT.md, check the available environment
and data, and continue from the agreed next step." This supplies context without
depending on the old computer's app history.

## 2. Copy the research files separately

Copy the following directories using an external drive, a private storage share,
or another file-transfer method. Sizes are uncompressed decimal totals and are
approximate. Keep the directory structure and original file bytes.

| Source on the old computer | What to preserve | Approximate size |
|---|---|---:|
| `D:\Doktorat\Platforma\data\pst900` | Download caches, original/derived images, manifests and presence pools | 4.12 GB |
| `D:\Doktorat\Platforma\data\urbaning-v2x` | Source identities, raw split archives, extraction and prepared catalog | 7.17 GB |
| `D:\Doktorat\Platforma\models` | All trained checkpoints and their provenance | 326 MB |
| `D:\Doktorat\Platforma\cache\torch` | Checksum-verified ImageNet initializer | 47 MB |
| Old checkout: `runs/` | Training histories, experiments, reports, previews and traces | 38 MB |
| Old checkout: `archive/*.zip` | Historical source/result snapshots | 18 MB |
| Old checkout: `outputs/` | Generated dataset workbook, builder and preview/check files; omit nested `node_modules/` | Less than 1 MB without dependencies |

The trained models and historical experiment reports cannot be recovered from a
fresh clone. Preserve them before retiring the old computer. `cache/pip`,
Matplotlib caches and `.venv` are reinstallable and are not needed for research
state. The raw UrbanIng archives and their extracted files are both retained;
this accounts for most of that dataset's current local disk usage.

On Windows, the simplest restoration uses the same
`D:\Doktorat\Platforma` data/model root and puts `runs/`, archive ZIPs and selected
`outputs/` files back under the new checkout. The checkout itself can have a new
path.

## 3. Check paths if the data root changes

- `configs/pstnet/experiment.json` contains the PST900 data, manifest, weights
  and counterfactual-cache paths. Put machine-specific variants under the
  Git-ignored `configs/local/` directory and pass `-Config` to `scripts/pstnet.ps1`.
- `configs/presence/perception_cnn.json` contains the old torch cache path.
  Presence launcher parameters and dataset/model paths are described in the
  [presence guide](PRESENCE_BASELINE.md).
- `scripts/urbaning.ps1` accepts `-DataRoot`; its default is
  `D:\Doktorat\Platforma\data\urbaning-v2x`.
- The PST900 segmentation manifest embeds absolute asset paths. Merely changing
  its location in a config does not relocate those assets. Preserve the old data
  root or regenerate the segmentation manifest with `pstnet prepare` at the new
  root. If you copied an existing `segmentation/manifest.json`, first preserve it
  under a different name: `prepare` reuses an existing manifest instead of
  rewriting its paths. Keep the original manifest and experiment provenance with
  old results.
- UrbanIng catalog asset keys are root-relative. Inspection reports still record
  the catalog's original absolute path, so generate a fresh report in a new output
  directory when using a different root.
- The existing v1 presence pools use relative payload paths, while provenance and
  saved experiment artifacts may record old absolute locations. Keep historical
  artifacts unchanged and use fresh output paths for new runs.

PowerShell entry points prefer the new checkout's `.venv` before the old machine's
fallback path. On another operating system, use the Python CLI entry points and
set paths appropriate to that machine.

## 4. Verify the restored project

```powershell
.\scripts\test.ps1
.\scripts\pstnet.ps1 -Action status
.\scripts\urbaning.ps1 -Action inspect `
  -DataRoot D:\Doktorat\Platforma\data\urbaning-v2x `
  -Output runs\urbaning_restored
```

Use a fresh report directory. `pstnet status` may report missing authors'
checkpoints: these were already unavailable on the source machine and are
different from our saved RGB pilot. This status is documented in the
[training guide](PSTNET_REPRODUCTION.md).

If you choose to re-download UrbanIng instead of copying it, use a new data root:

```powershell
.\scripts\urbaning.ps1 -Action fetch -DataRoot D:\Doktorat\Platforma\data\urbaning-v2x
.\scripts\urbaning.ps1 -Action extract -DataRoot D:\Doktorat\Platforma\data\urbaning-v2x
.\scripts\urbaning.ps1 -Action inspect -DataRoot D:\Doktorat\Platforma\data\urbaning-v2x
```

The default fetch selects the same single inspected sequence, not all 34
sequences. Published sizes and checksums are verified. See the
[UrbanIng guide](URBANING.md) for source identity and catalog details.

## Git scope

`.gitignore` excludes `/data/`, `/models/`, `/runs/`, `/outputs/`, `/migration/`,
local environment files, model checkpoint extensions, dependency directories and
historical archive ZIPs. Original inputs and model artifacts are preserved on disk.
Third-party source attribution and licenses remain in the repository.
