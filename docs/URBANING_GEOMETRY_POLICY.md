# Geometry and low-score partner acquisition

Implemented 2026-10-30 for cached offline policy fitting and comparison.
**No real-data geometry-policy fit or accuracy improvement has been measured.**
The running Ares baseline job 21540128 must remain on its existing checkout.
Use a separate checkout/branch after the job completes; do not pull new learning
or experiment modules into an executing experiment.

## Frozen hypothesis and input contract

Can partner geometry relative to low-score Car1 detections predict the benefit
of requesting Car2, Infra, or both better than the ego-summary baseline?
The existing 16-feature baseline is retained. The geometry model adds eight
features per available partner category, for **32 features total**:

- Peer origin x/y in the Car1 LiDAR frame, divided by 100 metres.
- Sine/cosine of the relative heading (radians after transform decomposition).
- Number of Car1 detections with score < 0.5, divided by 150.
- Minimum and score-weighted mean BEV distance from peer origin to those detections.
- Score-weighted mean cosine between Car1-to-object and peer-to-object vectors.

Object locations are mean box corners in the Car1 frame. Weights are 1-score.
Distance features are divided by 100 metres. Empty low-score sets produce zeros;
counts distinguish that case, and the original availability flags distinguish
absent peers. Coincident view vectors use a zero cosine convention. The 0.5
score cut is a fixed feature definition, not a calibrated error probability or
a test-tuned decision threshold. Headings do not impose a field-of-view rule.

Runtime features accept only Car1 boxes/scores/entropy, feasible source IDs and
explicitly shared peer-to-Car1 rigid transforms. No peer perception or GT enters
this interface. Pose beacons are an **additional pre-query metadata assumption**;
the original offline associations do not establish causal delivery, pose age,
bandwidth cost or synchronization in an online system.

**Infra limitation:** the official converter merges roadside LiDARs and uses the
site coordinate origin as its pose. Distance to this origin is only a geometric
proxy. It is not distance to the nearest roadside sensor, sensor visibility,
coverage, or evidence that a region is unoccluded. Car2 has an actual vehicle
LiDAR pose. A later physical sensor-footprint representation is a separate task.

## Cached workflow: no detector rerun

Export one pose sidecar per *completed* run, using the pinned upstream transform
implementation. Converted YAML hashes must match the stage1 trace. The exporter
composes YAML without constructing arbitrary Python tags and extracts only the
six lidar_pose scalars. Labels in the YAML never enter feature extraction.
The sidecar is bound to the complete frame trace hash, with exact frame and peer
coverage; input and sidecar hashes are retained in fitted-model provenance.

Run commands through the existing Ares container wrapper **inside a Slurm job**.
Generic example (replace the uppercase run paths with actual completed caches):

```bash
python scripts/urbaning_geometry.py --run TRAIN_RUN_1 \
  --upstream external/UrbanIng-V2X --output train1-poses.json
# Repeat for TRAIN_RUN_2, VALIDATION_RUN, and TEST_RUN, with distinct outputs.
# --converted-root ROOT supports relocated converted files with unchanged hashes.

python scripts/urbaning_subsets.py fit \
  --train-runs TRAIN_RUN_1 TRAIN_RUN_2 --validation-runs VALIDATION_RUN \
  --train-geometry train1-poses.json train2-poses.json \
  --validation-geometry validation-poses.json \
  --request-cost 0.05 --alphas 0.1 1 10 --output geometry-gain.json

python scripts/urbaning_subsets.py compare --runs TEST_RUN \
  --geometry test-poses.json --model geometry-gain.json \
  --output geometry-report.json
```

The four recording splits, frame selection, detector identity, three ridge heads
(including a separate both-partners head), F1-gain target, validation selection,
cost and random seeds remain as declared in the original protocol. All standard
and matched random controls are reused, including exact 0/1/2 query histograms.
Omitting geometry flags retains the original ego-feature workflow.

Fit and freeze the geometry model before inspecting test results. Compare the
two frozen policies on the same held-out frames, with quality, request counts
and budget-matched random controls. Do not tune the feature definition using
test gains. Geometry may fail: proximity does not guarantee visibility, and
fully missed objects do not supply low-score boxes.

This version supports cached fitting/replay only. The stage1 runtime
`--acquisition-model` path still supplies the original 16-feature interface and
does not accept geometry models. Existing completed caches can be reused while
their converted source YAMLs remain available; old NPZs alone lack peer poses.

## Validation

Five geometry tests cover known partner distances, joint rotation and ordering
invariance, missing/empty/invalid inputs, learning a synthetic distance signal,
trace binding, disjoint-recording fit/replay, feature-schema guards, and safe
pose extraction from YAML carrying unrelated Python tags. Existing UrbanIng
tests also pass. These are implementation checks, not real-data policy results.
