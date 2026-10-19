# UrbanIng-V2X: real sequence import and inspection

The current integration prepares **one real source sequence** for offline data
inspection. It does not train a detector, run acquisition decisions, or replace
the current PST900 segmentation experiment.

## Imported source

- Dataset: [UrbanIng-V2X](https://github.com/thi-ad/UrbanIng-V2X),
  [Harvard Dataverse DOI](https://doi.org/10.7910/DVN/A9LPY7), release **1.0**.
- Sequence: `20241126_0017_crossing1_00`, from intersection 1.
- Selected download: **3,573,073,745 bytes**, including two archive parts,
  sequence labels, vehicle metadata, track identity metadata and the HD map.
- Archive contents: **3,568,410,826 bytes** in **16,616 files**.
- Source inventory: **126,363,795,629 bytes** for all sequence archives;
  **132,159,774,986 bytes** for all published files including the digital twin.
  These are source download sizes, not a full preprocessing storage estimate.
- Downloaded public SDK reference: `urbaning==1.0.1`, wheel SHA256
  `59d9462608289f5a178bc1a27bedba056e7a1a348d0f3a52139850084d645c87`.

The importer uses standard Python, NumPy and Pillow, with optional DuckDB,
py7zr, OpenCV and Matplotlib. It does not import the full upstream SDK or install
OpenCOOD, Open3D or a different PyTorch environment. Geometry and camera
rectification follow the computations in the attributed upstream SDK. The
downloaded reference retains the authors' MIT copyright/license notices.

## Native files versus synchronized memberships

| Native stream category | Streams | Native files |
|---|---:|---:|
| Vehicle RGB | 12 | 4,814 |
| Infrastructure thermal | 6 | 3,721 |
| LiDAR, vehicle and infrastructure | 6 | 2,478 |
| Auxiliary vehicle navigation state | 2 | 5,600 |
| Total | 26 | 16,613 |

The remaining three extracted files are `calibration.json`,
`timesync_info.csv` and `weather_data.json`. The archive parts and external
label/support files are additional physical files retained in `raw/`.

There are **11,013 native perception observations** and **5,600 auxiliary
navigation records**. Navigation records are not automatically observations
owned by simulator agents. Native files include extra sweeps and pose history.

The source's transposed synchronization CSV has **200 anchors** and **26 stream
memberships per anchor**, or 5,200 memberships when complete. It does not define
one universal capture instant for those measurements. The adapter preserves
all native files independently of whether the provided table selects them.

Labels contain **152 tracks**, **25,250 timestamped 3D annotations**, and
**201 distinct label timestamps**. One endpoint label timestamp has no anchor
in the provided CSV. The annotation table retains it and sets
`source_anchor_available` to false. The importer neither fabricates another
source anchor nor drops those annotations.

The selected sequence contains 9 of the dataset's 13 source classes. This is
sequence coverage, not a redefinition of the full dataset taxonomy.

## Local storage

Data remains outside the OneDrive checkout:

```text
D:\Doktorat\Platforma\data\urbaning-v2x\
  source/                 frozen metadata, SDK reference and download identities
  raw/                    original split archives, labels and supporting files
  extracted/<sequence>/   unchanged unpacked source files and completion marker
  prepared/<sequence>/inspection-v1/
    observations.{jsonl,parquet}
    assets.{jsonl,parquet}
    streams.{jsonl,parquet}
    associations.{jsonl,parquet}
    annotations.{jsonl,parquet}
    geometry.{jsonl,parquet}
    manifest.json
```

The prepared catalog is an **experimental adapter contract**, named
`phdsim-urbaning-inspection-catalog-v1`. It is not the final general v2 loader
proposed in [the cross-dataset audit](DATASET_AUDIT.md). Source images and point
clouds are referenced through root-relative keys rather than copied into the
catalog. A deployment supplies the `urbaning-v2x` storage-root mapping.

The JSONL and Parquet outputs describe the same six logical tables. JSONL is
retained for readable inspection; Parquet supports typed SQL queries. UTC
nanoseconds are preserved as integers, separately from source millisecond
strings. A release completion manifest records table counts and hashes.

## Commands

Install the optional import/inspection dependencies in the project environment:

```powershell
python -m pip install -e ".[urbaning]"
```

Use explicit actions; inspection does not trigger a download or training:

```powershell
.\scripts\urbaning.ps1 -Action fetch
.\scripts\urbaning.ps1 -Action extract
.\scripts\urbaning.ps1 -Action inspect -Frame 100 -Output runs\urbaning_inspection
```

Equivalent portable Python CLI, with an explicit data root:

```text
phdsim urbaning fetch --root /allocated/project/urbaning-v2x
phdsim urbaning extract --root /allocated/project/urbaning-v2x
phdsim urbaning inspect --root /allocated/project/urbaning-v2x --frame 100 --output runs/urbaning_inspection
```

Downloads resume partial files only when the server honors the requested byte
range. Published source sizes and MD5 checks are verified; SHA256 identities are
also recorded locally. Completed files with a mismatched identity are rejected
rather than overwritten. Extraction publishes its completion marker after
success; incomplete directories are preserved for diagnosis.

Choose a fresh report output directory for another completed inspection. Source
release snapshots and catalog identities are kept separate from report paths.

## Code responsibilities

| Module | Responsibility |
|---|---|
| `datasets/urbaning/source.py` | Select one source sequence, resumable public download, byte/hash verification |
| `datasets/urbaning/archive.py` | Bounded split-7z extraction and completion marker |
| `datasets/urbaning/catalog.py` | Native asset inventory, exact timestamp handling, source associations and Parquet/JSONL export |
| `datasets/urbaning/labels.py` | Convert track-wise 3D supervision to timestamped offline annotations |
| `datasets/urbaning/geometry.py` | Directed sensor/world transforms, camera models, projections and native LiDAR decoding |
| `datasets/urbaning/preview.py` | Rectified camera/label overlays, LiDAR top-down view and timing plot |
| `datasets/urbaning/inspection.py` | Inspection orchestration and report |
| `cli/urbaning.py` | Explicit data workflow arguments |

## Validation and scientific limits

Native bytes are hashed, and payload profiles are decoded at the first, middle
and last native sample of each stream. This is not an exhaustive semantic
validation of every decoded payload. The selected preview decodes all six
LiDARs and selected camera views.

Camera rectification was compared with the SDK's unmodified pure functions for
all **18 cameras**, using one real frame per camera, covering pinhole and fisheye
models. Pixel and resulting intrinsic-matrix differences were **zero**. The
reference identity and results are retained in `source/rectification-parity.json`.
This confirms matching rectification computations, not independent accuracy of
the dataset's physical calibration.

The previews show **reference annotations**, not predictions. The point-cloud
overview is a geometric aggregation for inspection. Vehicle poses are sampled
using the same preceding-10-ms rule as the upstream SDK at the sensor's own
timestamp. The preview adds no new per-point motion compensation or object
motion interpolation. Native point-time offsets remain in the NPZ payloads.

The provided association table can select images captured after its anchor.
A future online experiment must explicitly define its decision time, input
availability and maximum observation age. Calibration does not make RGB and
thermal views pixel-aligned. Roadside mount groups are retained from source name
prefixes, while physical platform identity currently distinguishes vehicles and
the infrastructure site; pole identities still need explicit confirmation.

Ground truth is isolated in the annotation table. The whole inspection catalog
is an offline preparation artifact, not an unrestricted input view for a policy.
Agent assignment, per-agent observation limits, detector training, fusion and
learned acquisition remain separate future steps.
