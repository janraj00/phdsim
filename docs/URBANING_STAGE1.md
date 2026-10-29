# UrbanIng stage 1: frozen LiDAR acquisition baseline

For joint none/Car2/Infra/both acquisition, a gain predictor and matched random
controls, see the [subset policy protocol](URBANING_SUBSET_POLICIES.md).
`phdsim urbaning subsets` fits and compares policies using saved counterfactual
predictions. The runner below accepts a frozen model via `--acquisition-model`;
that option does not change its offline counterfactual scope.

Status: **implemented runner, passing CPU contract tests and real-data CPU smoke
evaluation**. Full held-out benchmark evaluation remains pending. Results and
their scope are recorded in [UrbanIng experiment status](URBANING_EXPERIMENTS.md).

The experiment uses the authors' [CoBEVT release v1.0.0](https://github.com/thi-ad/UrbanIng-V2X/releases/tag/v1.0.0),
`CoBEVT_SIS_1_2_vs_3`, and an external [upstream checkout](https://github.com/thi-ad/UrbanIng-V2X)
at `d5766e75f985c6c566a09abfa23d3fbb32f03820`. The release contains
`best_model.pth`, its configuration and the authors' reference results.
Archive and member SHA256 checks are mandatory. Weights load strictly and remain
frozen; no retraining or checkpoint conversion is required.

## Protocol

For the completed pilot, Car1 (`100000`) performs the detection task,
Car2 (`200000`) is the other vehicle, and Infra (`-1` at crossing1) is the
bundled infrastructure site. These are platform names; `ego` remains the
implementation's reference-agent role. Selecting Car2 as the reference agent
would swap the vehicle roles, not rename the platforms. All inputs below are LiDAR.

| Code action | Sources for the Car1 pilot |
|---|---|
| `ego` | Car1.LiDAR |
| `vehicle_peer` | Car1.LiDAR + Car2.LiDAR, if Car2 is within communication range |
| `infrastructure` | Car1.LiDAR + Infra.LiDAR, if available |
| `all` | Car1.LiDAR + all available Car2/Infra inputs |
| `random_one_peer` | Car1.LiDAR + one uniformly selected available partner |
| `entropy_gate` | Car1.LiDAR alone, or one partner when Car1 entropy exceeds a fixed threshold |

The official converter assigns vehicle IDs `100000`, `200000`, and infrastructure
IDs `-1`, `-2`, `-3` for the three crossings. **A site merges its roadside LiDAR
clouds into one source**. This stage does not select individual poles or sensors.
The upstream 70m filter uses source poses, including the site's origin. We retain
that convention and log included/excluded sources rather than interpreting it as
distance to each roadside sensor.

Every variant uses the same frame and the same all-source ground truth. It is the
upstream visibility-filtered union of objects from eligible sources, including
the released minimum LiDAR-hit requirement; it is not all native annotations.
Each frame is preprocessed once. The adapter selects voxels, remaps agent indices,
and changes `record_len`; architectural `max_cav=3` and masks remain unchanged.
Only voxels and `record_len` enter the model. Missing peer categories fall back
to ego, so all baseline denominators remain paired; fallback counts are reported.
Empty sources or singleton total voxel inputs fail explicitly because upstream
scatter/PillarVFE cannot reliably represent those cases.

Acquisition is **offline counterfactual replay**, not an online transport system:
all observations are loaded to establish all possible outcomes. The selector
interface receives only ego entropy, frame identity, source IDs and a fixed seed.
It never receives labels, peer predictions or measured gains. Random partner
selection is repeatable and shared between the gated and always-one baselines.
Entropy is mean Bernoulli entropy of the 100 highest ego anchor confidence values
after the upstream max over four sigmoid classes. It is an uncalibrated heuristic;
it is not a probability that detection is wrong. Low entropy does not establish
that an occluded or missed object is absent.

Metrics are globally confidence-sorted VOC AP at **BEV polygon IoU** 0.3, 0.5,
0.7, per class and macro-average, with the released rectangular ROI and upstream
0–100m corner-radius filter. Despite the upstream filename `eval_3d_det.yaml`,
the matched overlap is BEV, not volumetric 3D IoU. Missing classes yield `null`
AP/macro-AP rather than a misleading score on tiny subsets. Global sorting may
differ from authors' default evaluation ordering; this is not yet a reproduction
of the paper's full test benchmark. `all` is a comparator, not a guaranteed upper bound.

Cost is currently **number of requested peer bundles**. Forward times exclude
preprocessing, transfer, entropy calculation and postprocessing, and include
cold-start effects. They are diagnostic timings, not end-to-end acquisition
latency. No measured network byte/latency savings or calibrated utility is claimed.
The always-one baseline is not rate-matched to a gate that sometimes stops.

## Fetch the model and prepare one source sequence

In the main phdsim environment (Python 3.11+):

```bash
python -m pip install -e '.[urbaning-stage1]'
phdsim urbaning cobevt fetch
git clone https://github.com/thi-ad/UrbanIng-V2X.git external/UrbanIng-V2X
git -C external/UrbanIng-V2X checkout d5766e75f985c6c566a09abfa23d3fbb32f03820
```

`external/` is local, ignored work. Keep the checkout's tracked files unchanged.
The standalone runner below works without installing phdsim into the legacy
upstream environment. It sets `PYTHONHASHSEED=0` before Python starts.

Use the already extracted native sequence if it is present. Otherwise fetch and
extract that one sequence using the existing importer (requires the `urbaning`
extra). A dataset on the former Windows machine is not automatically on the Mac
or a remote GPU node:

```bash
phdsim urbaning fetch --root data/urbaning-v2x --sequence 20241126_0017_crossing1_00
phdsim urbaning extract --root data/urbaning-v2x --sequence 20241126_0017_crossing1_00
phdsim urbaning opencood-view --root data/urbaning-v2x \
  --sequence 20241126_0017_crossing1_00 --start-frame 100 --max-frames 10 \
  --output data/urbaning-converter-input
```

The view uses symlinks to immutable native files, with verified label metadata.
With a frame limit/offset, only a derived synchronization CSV is written; original
column identities and source bytes remain intact. Omit both options for the full
sequence. For this recording, the beginning has the other vehicle outside 70m;
the middle fragment is useful for exercising all three inputs.
It preserves the source manifest, calibration hash and exact synchronization
associations, including integer nanosecond anchors. Native LiDAR per-point times
remain in the original payloads. Converted OpenCOOD frame IDs are **indices**,
not reconstructed capture timestamps. The official conversion is an offline
association and can use samples captured after an anchor; do not call it causal replay.

Install the pinned external SDK's `urbaning/` package in a separate Python 3.10+
environment with its declared conversion dependencies, then run from phdsim:

```bash
python scripts/urbaning_convert.py --upstream external/UrbanIng-V2X \
  --source-view data/urbaning-converter-input --output data/urbaning-opencood-smoke
```

This invokes the official converter unchanged, on just the selected sequence.
It also converts camera files; these are not inputs to the LiDAR model. Source
and conversion output remain separate. A failed conversion is retained for
inspection and requires a new output directory on retry.

## Run on CPU or GPU

A Linux x86_64 CPU environment is also supported explicitly. For a fresh Python
3.12 environment, the direct dependencies used here are recorded in
`requirements/urbaning-stage1-cpu.txt`:

```bash
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements/urbaning-stage1-cpu.txt
```

The manifest is a direct-dependency profile, not a full transitive lock or a
verified macOS/Apple Silicon installation. The upstream SDK conversion and model
runtime can share this CPU environment. GPU execution uses `--device cuda`
(the default) and still needs a compatible CUDA PyTorch build.

For GPU runs, use a **separate Linux OpenCOOD environment**, with a PyTorch/CUDA build compatible
with the actual GPU, `spconv`/`cumm`, Open3D, OpenCV, NumPy, SciPy, Shapely, PyYAML,
einops and the compiled upstream `box_overlaps` extension. The authors document
Python 3.9 / PyTorch 1.12 / CUDA 11.3, but their requirements contain conflicting
old pins; that is not a verified one-command install for a new GPU. Do not put
those requirements into phdsim's PSTNet environment. No GPU environment has been
built or validated by this implementation session.

Build the Cython extension from the external checkout's `opencood` project directory
with `python opencood/utils/setup.py build_ext --inplace`. Use `CC=gcc CXX=g++`
when the interpreter's configured compiler is unavailable. Cython regenerates the
tracked `opencood/opencood/utils/box_overlaps.c`; after the build, restore that
generated C file from the pinned commit, keeping the built extension. This
preserves the tracked-source check. No hand changes to the upstream `.pyx` are needed.
This detection path uses CPU polygon NMS and CPU spconv voxelization. Apple MPS
and native macOS dependency installation remain unvalidated.

With the chosen environment active, run from the phdsim repository root.
For a CPU smoke test:

```bash
python scripts/urbaning_stage1.py doctor --upstream external/UrbanIng-V2X --device cpu
python scripts/urbaning_stage1.py run --upstream external/UrbanIng-V2X \
  --data-root data/urbaning-opencood-smoke --sequence 20241126_0017_crossing1_00 \
  --purpose smoke --max-frames 10 --ego-id 100000 --seed 42 \
  --device cpu --cpu-threads 2 --entropy-threshold 0.5 --output runs/urbaning-stage1-smoke-001
```

The threshold 0.5 is a fixed diagnostic example, **not a tuned recommendation**.
Omit it to run only reference variants and random-one-peer. `doctor` returns exit
code 2 until dependencies, source pin, model and the requested device are ready.
No silent device fallback is used. Each run refuses to overwrite an existing output directory.

Outputs:

- `run.json`: arguments, effective configuration, model/source identities,
  environment and `running`/`completed`/`failed` state.
- `frames.jsonl`: exact source identities and hashes, shared GT fingerprint,
  selected actions, ego entropy, source associations when available, and timings.
- `predictions/*.npz`: shared ground truth and boxes/scores for each reference
  action. Policy choices point to those same cached outcomes.
- `metrics.json`: paired per-variant AP, class support, request counts and
  unavailable-partner fallback counts. Written only after successful completion.

First run is a **smoke test on crossing1/2**, not a generalization result. The
released checkpoint holds out crossing3. The runner rejects crossing3 smoke runs
and rejects `evaluation` on crossing1/2. Use the authors' recording splits when
calibrating thresholds; do not randomly split neighboring frames. Once decisions
are frozen, use `--purpose evaluation` on crossing3 sequences, with `--max-frames 0`
for each complete sequence. Current reports are per sequence; a full benchmark
must aggregate detections across all held-out recordings and both ego vehicles,
not average per-sequence AP. That full run and aggregation are still pending.

## Verification

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_urbaning*.py'
PHDSIM_URBANING_UPSTREAM=external/UrbanIng-V2X \
PHDSIM_URBANING_MODEL=models/urbaning/CoBEVT_SIS_1_2_vs_3 \
PYTHONPATH=src python -m unittest discover -s tests -p test_urbaning_cobevt_integration.py -v
```

The opt-in integration test needs CPU PyTorch, einops, Shapely, NumPy and PyYAML.
It loads all **9,736,008** model parameters strictly, runs synthetic inputs through
the full released architecture at its native BEV size for all four source
subsets, and checks the upstream AP adapter on known boxes. It complements the
small real-data CPU smoke evaluation; it does not establish full-benchmark
detection quality or validate GPU execution.

No upstream implementation or model binary is redistributed in Git. The external
repository includes OpenCOOD files with their own license notices; preserve them.
