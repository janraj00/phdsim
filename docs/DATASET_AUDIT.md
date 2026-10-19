# Dataset compatibility audit and proposed data contract

Reviewed on **2026-10-18**. Status: **design proposal, not an implemented v2
loader or a completed dataset import**.

Follow-up on the same date: [one real UrbanIng-V2X sequence](URBANING.md) has
been downloaded and unpacked for an experimental catalog/geometry inspection.
The scope statements below describe the original documentation audit; that
follow-up provides additional real-file evidence without implementing general v2.

## Outcome and evidence scope

The current observation pool is a useful foundation for paired images, but it
does not yet describe all 25 candidate datasets without losing meaning. The
largest gaps are physical sensor identity, time semantics, coordinate systems,
explicit observation associations, typed payloads, and task-specific annotations.

This audit compares the actual v1 code with the supplied dataset landscape and
public documentation, schemas, and selected SDK files from the dataset authors.
PST900 is also supported by the existing local import. Other datasets have **not**
been downloaded, decoded, or validated against their complete archives in this
audit. A documentation match is not evidence of a working adapter. Byte layouts,
clock conversions, calibration directions, release contents, and annotation
coverage need a small real-data import before being declared supported.

The supplied inventory has 25 rows. Its SHA256 is
`9e6dc9397e57659158a6b10df9faa2a5fb1c6247644e2338c97597383ec48d4e`.
The CSV is an input to the investigation; its recommendations are not project
requirements. Source links below identify the evidence for each dataset.

## What v1 actually supports

Inspected implementation:

- [Generic pool](../src/phdsim/datasets/pool.py): `PoolRecord`,
  `validate_records`, `ObservationPool`, and `prepare_pool`.
- [Allocation](../src/phdsim/datasets/allocation.py): `Assignment`, `Schedule`,
  and `allocate`.
- [PST900 segmentation manifest](../src/phdsim/datasets/pst900/segmentation.py).
- [Current data contracts](DATA.md).

| Existing field or rule | Keep | Limitation revealed by the audit |
|---|---|---|
| `observation_id`, pool-level dataset identity | Stable identity and integrity checks | IDs need dataset/release namespaces when multiple pools share a catalog. Preserve original IDs too. |
| `sequence_id` | Original recording grouping | Also preserve session, route, location, and physical platform identities where supplied. These are not interchangeable. |
| `stream_id`, `modality` | A stream is not a simulator agent | No registry defines which physical sensor/platform produced the stream, its representation, or its coordinate frame. |
| `tick` | Source ordinal when that is what it means | A required common tick cannot represent arbitrary asynchronous streams and event/scan intervals faithfully. Simulation ticks belong to allocation. |
| `target` | Explicit task reference is useful | All observations at a v1 frame must share one target. A target alone says nothing about geometric alignment or view-specific label applicability. |
| `capture_time_ns` | Nullable integer time | No clock, original unit, timestamp meaning, interval, precision, or synchronization method. Arrival time must not be renamed capture time. |
| `calibration_ref`, `pose_ref` | Keep external references | Currently only paths to opaque local files. Frame names, transform direction, units, timestamps, validity, and whether a pose is ground truth are undefined. |
| `payload.path`, `format`, `sha256` | Immutable assets and checksums | No typed array/channel description, encoded byte count, storage resolver, container selector, or raw/derived lineage. |
| `split` | Preserve original partitions | Only `train`, `validation`, `test` are allowed, and each sequence must have one split. Multiple official split protocols, additional test domains, and unlabeled samples do not fit cleanly. |
| Separate `labels.jsonl` | Keep supervision outside observations | Generic label values are opaque. The presence consumers assume binary labels; segmentation uses a different PST900 manifest. No universal task/annotation schema exists. |
| One observation per `(sequence, tick, stream)` | Useful for an explicitly sampled replay | Native streams can contain many messages in a decision interval. Sampling/windowing must be declared rather than discarded during import. |
| Pool-local files and SHA deduplication | Integrity and bounded path resolution | `prepare_pool` copies files. `ObservationPool` materializes every row, checks local paths eagerly, and fingerprints an in-memory serialization. This is not a scalable remote catalog. |

The PST900 segmentation workflow is a **second, dataset-specific contract** with
fixed RGB/thermal/mask assets and absolute local paths. It is not already an
instance of a general multi-dataset v2 schema.

## Coverage of all 25 candidates

The third column is a proposed design response to the documented source facts.
It is our engineering inference, not a statement that the source already uses
these PHDSIM field names. None of these rows certifies a new adapter.

| Dataset and primary source | Documented characteristics relevant to import | Required representation or unresolved adapter work |
|---|---|---|
| [Caltech Aerial RGB-Thermal](https://github.com/aerorobotics/caltech-aerial-rgbt-dataset) | Labeled pairs and thermal-only samples; `thermal8`/`thermal16`; rectified labeled images; random, geographic, and temporal split protocols. | Store dtype and representation lineage, optional pairing, rectification state, annotation taxonomy/ignore IDs, and named split sets. Check raw synchronization details, which the README leaves incomplete. |
| [M2DGR](https://github.com/SJTU-ViSYS/M2DGR) | Many cameras, infrared, LiDAR, event and inertial/GNSS streams in ROS bags; differing sensor rates; trajectory supervision. | Sensor/platform registry, source topic/message identity, independent times and event windows, calibration graph, and a localization task. Do not invent segmentation labels or pair streams by row number. |
| [The Great Outdoors](https://unmannedlab.org/the-great-outdoors-dataset/) | UGV data with multiple RGB views, LWIR, LiDAR, radar, navigation streams, raw ROS bags, and semantics. | Multi-view and per-point/per-image annotation scopes, transform/trajectory references, and source ontology version. Resolve class-count disagreement in the website against released label definitions before import. |
| [SEW Multimodal AMR](https://github.com/SEW-Eurodrive-Open-Source/Multimodal_AMR_dataset) | Current documentation is the 2026 release, unlike the CSV's 2025 name. Includes ultrasonic, two laser scanners, ToF/NIR, RGB, thermal, radar, preceding unlabeled frames, and 2D/3D labels. | Versioned source release; range/event/array payload profiles; raw-versus-derived lineage; per-view annotations and history membership. See the synchronization and parallax findings below. |
| [CMHT Autonomous](https://pmc.ncbi.nlm.nih.gov/articles/PMC12175244/) | Original paper describes ROS2 bags plus PNG, PCD, text navigation data and JSON labels/calibration, including 3D tracklets. | Preserve original sensor times, capture conditions, object/track IDs and calibration. Confirm per-drive synchronization and coverage from original files. The independently repackaged [MCAP release](https://huggingface.co/datasets/Voxel51/cmht-autonomous-driving) must retain its own derivative identity. |
| [MUSES](https://github.com/timbroed/MUSES) | Frame camera, LiDAR, radar, events and GNSS/IMU; panoptic/semantic/uncertainty ground truth; clear-condition reference images; hidden test labels. | Time windows and motion-compensation lineage, typed task annotations, reference-image relationship, and annotation-availability state. Ground-truth uncertainty is offline supervision, not a policy input. A clear reference is not a simultaneous peer observation. |
| [Seeing Through Fog](https://github.com/princeton-computational-imaging/SeeingThroughFog) | Visible, NIR/gated, FIR, radar and LiDAR; 2D/3D labels with a KITTI extension; weather-based splits and raw-image conversion tools. | Distinct sensor/representation profiles, explicit pairing and projection, original rotation conventions, environmental context and split protocol. The legacy Princeton URL in the CSV did not load; use the authors' repository. |
| [View of Delft](https://tudelft-iv.github.io/view-of-delft-dataset/docs/SENSORS_AND_DATA.html) | Asynchronous capture packaged into associated frames with a 40 ms tolerance; motion-compensated LiDAR/radar; radar variants accumulating 1, 3 or 5 scans. | Native times, association tolerance and compensation provenance. Radar points include RCS, radial velocities and a scan-relative time ID. Accumulated scans are derived history, not additional independent sensors. |
| [nuScenes](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md) | Separate sample, sensor sample, calibrated sensor, ego pose, instance and annotation tables; 2 Hz annotated keyframes and intervening sensor samples. | Preserve source tokens, keyframe flag, stream ordering and global-frame annotations. A non-keyframe can reference a later sample in the source schema; membership must not imply causal availability. |
| [Oxford Radar RobotCar](https://oxford-robotics-institute.github.io/radar-robotcar-dataset/documentation) | Radar polar PNGs embed per-azimuth time/angle/validity metadata; LiDAR raw PNG and binary variants; odometry and repeated routes. | Sensor-aware decoders, per-element timing/validity, native coordinates, raw/derived links and source-specific units. A PNG extension does not imply a photograph. |
| [Boreas](https://github.com/utiasASRL/pyboreas) | Camera, radar and LiDAR are explicitly nonsynchronous; accurate per-message timestamps and poses; LiDAR has time/ring-related channels; test pose ground truth may be absent. | Independent times, typed point fields, temporal transforms and annotation availability. Preserve float64 global poses; distinguish measured navigation from privileged reference trajectories. Pin Boreas separately from Boreas-RT. |
| [RADIATE](https://pro.hw.ac.uk/radiate/doc/dataset/) | Camera, LiDAR and radar operate at different rates. Recorded timestamps are arrival times. Labels are rotated boxes in radar imagery; polar/Cartesian radar images are provided. | Timestamp-kind field, image-to-metric geometry, radar representation lineage, and annotation frame/angle convention. Native absence/degradation is retained. Do not imply camera-pixel or 3D box annotations from radar labels. |
| [RaDelft](https://github.com/RaDelft/RaDelft-Dataset) | Radar processing levels, camera, LiDAR and odometry; generated radar point clouds only for some scenes; automatic semantic labels in cube form. | Typed tensor dimensions, processing lineage and availability, label-generation provenance, and split-aware derived assets. Generated outputs are not new physical sensor measurements. Access requires a source-specific request. |
| [A2D2](https://a2d2-dataset.github.io/) | Six cameras, five LiDARs, registered depth, automotive bus data, multiple annotation types and a larger sequential set. | Sensor/view identity, registration and derived-depth lineage, per-task coverage and source sequence grouping. Do not infer that every sequential frame has every annotation type. |
| [DeLiVER](https://github.com/InSAI-Lab/DELIVER) | Synthetic benchmark with RGB, depth, LiDAR, events, weather and sensor-failure cases. Benchmark describes six views; README specifically announces the front-view release. | Simulation/condition identity, source scene and view, derived HHA versus depth, and payload profile. Inspect the chosen release for actual view/event representations; do not assume all six views or raw event streams are downloaded. |
| [FLIR ADAS](https://oem.flir.com/en-150/solutions/automotive/adas-dataset-form/) | Current page describes unequal RGB/thermal still-image counts, matched video frames, pre-AGC thermal and AGC image variants, and COCO/Conservator annotations. | Pin original versus expanded release; explicit source pairing and per-view boxes; distinguish valid bit depth, storage dtype and AGC. Timestamp pairing does not establish pixel alignment. Download access uses the publisher's form/account. |
| [KAIST Multispectral Pedestrian](https://github.com/SoonminHwang/rgbt-ped-detection) | Beam-splitter RGB/thermal pairs, temporal pedestrian boxes and day/night sequences. Authors warn about differing evaluation settings. | Sequence/track IDs, annotation release identity, image-coordinate box conventions and evaluation subset. Preserve documented alignment without treating every RGB-T dataset as equivalent. The CSV points to a fork; use the authors' repository. |
| [PST900](https://github.com/ShreyasSkandanS/pst900_thermal_rgb) | Existing local import: aligned 8-bit RGB/thermal and five-class masks; source ordinal but no imported physical timestamp; actual archive contains 885 pairs. | Migration reference for v1. Preserve mask coordinates, unknown physical time, registration provenance, original partitions and mirror checks. Keep whole-frame presence labels as a separate derived task. |
| [DAIR-V2X](https://github.com/AIR-THU/DAIR-V2X/blob/main/docs/get_started.md) | Vehicle and infrastructure data have separate IDs; calibration chains include vehicle navigation/world frames; camera-time and cloud-time labels differ; cooperative labels also exist. | Physical source identity, explicit cross-source associations, timestamp-specific annotations, transform direction and separate annotation scopes. A shared integer filename cannot replace the cooperative pairing table. |
| [V2X-Seq](https://github.com/AIR-THU/DAIR-V2X) | Separate sequential perception (SPD) and trajectory forecasting (TFD) products; maps, trajectories and traffic lights. SPD preserves vehicle/infrastructure pairs and annotation-time conventions. | Treat SPD/TFD as separate products/task profiles. Store track/history/future-label intervals and map references. Forecast labels must not become currently available observations. |
| [V2V4Real](https://github.com/ucla-mobility/V2V4Real) | Real cooperative perception/tracking; OPV2V-format data and a separate KITTI release; configurable asynchronous evaluation. | Platform/sensor identity, source format version, coordinate transforms and track scope. Record benchmark-injected delay separately from measured sensor timing. Confirm camera contents for the selected distribution. |
| [TUMTraf-V2X](https://tum-traffic-dataset.github.io/tumtraf-v2x/) | Onboard/roadside sensors; 3D boxes with track IDs, OpenLABEL labels, navigation and HD maps. | OpenLABEL stream/frame/transform mapping, source role, temporal object identity, and annotation applicability. Cross-view fusion needs geometric transformation rather than matching image pixels. |
| [UrbanIng-V2X](https://thi-ad.github.io/urbaning/) | Two vehicles and multiple roadside poles; vehicle RGB and infrastructure thermal/LiDAR; calibrated relationships across several intersections. | Distinguish vehicle, pole, sensor and view IDs; shared scene/world geometry; per-source coverage. Choosing a thermal peer can change both modality and viewpoint. Preserve these factors separately. |
| [OPV2V](https://opencood.readthedocs.io/en/latest/md_files/data_intro.html) | Simulated scenarios contain physical vehicle IDs, four cameras, PCD and YAML per step; YAML mixes calibration, poses, objects and future planning. | Preserve simulation source identities and physical times only when specified. Separate supervision/future information from observable metadata; record pose noise as an experimental transformation. |
| [V2XSet](https://github.com/DerrickXuNu/v2x-vit) | Simulated vehicle/infrastructure data; OPV2V-style organization; communication/localization noise added in postprocessing. | Physical source role and noise/delay provenance. The CSV repository is a fork; use upstream documentation. Injected latency belongs to the experiment, not a fabricated measured capture timestamp. |

### Findings that directly change the schema

1. **Association and alignment are different facts.** SEW groups measurements
   within 40 ms, but RGB/thermal registration is exact only at a reference
   distance of 1.5 m and retains depth-dependent parallax. Store temporal pairing
   and spatial registration independently. [SEW documentation](https://github.com/SEW-Eurodrive-Open-Source/Multimodal_AMR_dataset)
2. **One timestamp is insufficient.** Boreas explicitly keeps asynchronous
   sensor samples; RADIATE records arrival times. Keep a timestamp's meaning and
   clock, not just an integer named capture time. [Boreas SDK](https://github.com/utiasASRL/pyboreas),
   [RADIATE format](https://pro.hw.ac.uk/radiate/doc/dataset/)
3. **Encoding does not define modality.** Oxford radar PNGs contain measurement
   metadata as well as returns. Image normalization would corrupt their meaning.
   [Oxford format](https://oxford-robotics-institute.github.io/radar-robotcar-dataset/documentation)
4. **Stored variants can share the same measurement.** View of Delft's multi-scan
   radar aggregates reuse history. Lineage must identify the component scans so
   acquisition cannot count the same evidence as several independent sensors.
   [VoD format](https://tudelft-iv.github.io/view-of-delft-dataset/docs/SENSORS_AND_DATA.html)
5. **Task labels have a frame and a time.** DAIR-V2X distinguishes labels for
   camera and point-cloud capture times as well as cooperative labels. A single
   opaque label attached to an arbitrary shared frame loses this distinction.
   [DAIR layout](https://github.com/AIR-THU/DAIR-V2X/blob/main/docs/get_started.md)
6. **Source associations can point ahead in time.** nuScenes associates some
   non-keyframe sensor samples with the following annotated sample. Import the
   relationship, but enforce decision-time availability separately.
   [nuScenes schema](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md)

## Proposed logical contract

Use a small common core with typed modality/task profiles and independent
registries. The tables below are logical entities, not a requirement to run a
database server or create a file for every table in a tiny local dataset.

| Entity | Essential content |
|---|---|
| Dataset release | `dataset_id`, `release_id`, upstream revision/checksum, product/subset, source URL, schema version, adapter revision, import configuration and license/access reference |
| Recording / sequence | Source recording/session/sequence IDs, location/route where supplied, source ordering, clock definitions and known coverage |
| Physical platform | `platform_id`, source ID, type/role such as vehicle, robot or roadside pole; fixed/mobile status when known |
| Sensor / stream | `sensor_id`, `platform_id`, `stream_id`, modality, view, native frame, payload profile and processing/representation identity |
| Observation | Globally scoped ID, release/sequence/stream reference, original frame/message ID, source ordinal if supplied, typed time reference, asset references and provenance |
| Asset / representation | Immutable identity, logical storage key and selector, media encoding, dtype/shape/channel profile, encoded byte count, checksum scope and derived-from references |
| Association | Observation members, anchor, relation type, matching method, known time offsets/tolerance, spatial registration state and geometry reference |
| Geometry | Coordinate frame graph, intrinsics/distortion, directed transforms, units/conventions, validity times, trajectory references and provenance/uncertainty where provided |
| Task / annotation | Task/version, taxonomy and ignored classes, annotation type, target observation/group/object, coordinate frame and reference time, availability and supervision provenance |
| Split set | Named protocol/version, original split names and memberships, grouping/leakage policy and independent experiment-role assignments |

### Identity and physical ownership

`platform_id` identifies a real or simulated source platform in the dataset.
`sensor_id` identifies its sensor. `stream_id` identifies a recorded or derived
stream. `agent_id` remains solely in the experiment allocation.

A single platform with an RGB camera and a thermal camera can supply two
single-modality simulator agents. Assigning them to two agents does not create
two physical viewpoints. Multi-vehicle data must retain its actual source
geometry. Cross-dataset observations are not co-located or synchronized merely
because their source frame numbers match.

Some datasets do not identify the physical rig unambiguously. A dataset-scoped
logical rig ID may be used with `identity_kind = adapter_assigned`; it must not
claim a measured vehicle identity or pose.

### Time and allocation

The time profile needs:

- Original timestamp value/unit, `clock_id` and kind such as capture, arrival,
  hardware stamp, simulation time or unknown.
- Optional normalized integer-nanosecond timestamp plus a documented clock
  mapping, epoch and known precision. Nanosecond units do not imply nanosecond
  measurement accuracy. Do not convert through floating-point seconds.
- Optional measurement interval for exposures, scans and event packets, plus
  per-element timestamps in the payload profile when available.
- Source ordinal independently of physical time. Unknown values remain null.
  Relative times may be signed if the chosen origin requires it.

Allocation selects observations or explicitly constructed windows for decision
ticks. It records the sampling/matching rule, age limit, missing-data behavior,
and per-agent counts. The user's one-observation-per-agent-per-tick rule applies
here, after native data has been preserved. A window is a documented derived
observation with its component IDs, not an undocumented merge of modalities.

Runtime availability is distinct from measurement time. Source arrival time,
replay delivery time and injected communication delay have separate provenance.
Policies may only request observations available under the declared protocol.
The current same-frame PST900 protocol remains a special case.

### Geometry, representation and annotations

Transforms need explicit `from_frame`, `to_frame`, translation units, rotation
representation/order and validity. Choose one documented normalized convention
and retain the original representation for traceability. Intrinsics belong to
the relevant image representation: resizing, rectification and cropping change
them. Global poses retain appropriate precision and source identity.

Payload profiles describe images, point clouds, radar tensors, event packets,
range scans and navigation messages. Examples of required semantics include
RGB/BGR order, thermal AGC state and valid bit depth, depth scale and invalid
values, point-channel names and units, radar polar axes, and event polarity/time.
Unknown temperature calibration must never be presented as Celsius.

Multiple stored representations may reference one physical measurement. An
accumulation, projection, inpainting operation, model output, or pseudo-label
records its parents, processing configuration and model identity when relevant.
Do not make raw and processed forms independent acquisition candidates by default.
Transfer cost uses the selected transmitted representation and its encoding;
archive size and uncompressed tensor size are different quantities.

Annotation profiles cover masks, 2D/3D boxes, tracks, pose/trajectory references,
panoptic instances and uncertainty labels. Preserve each dataset's taxonomy and
void/ignore rules. Cross-dataset class mapping is a separate versioned task
definition. Empty annotations, absent annotations and withheld annotations must
remain distinguishable.

Ground truth, future trajectories, clear-condition reference images, generated
teacher gains and privileged poses are available only to their declared offline
consumers. Weather tags, calibration and estimated poses are exposed to a policy
only if the experiment explicitly permits them. A queryable catalog must not
become the policy's unrestricted runtime input.

### Example observation and association

The following records are **illustrative synthetic metadata**, not downloaded
dataset samples or a finalized JSON Schema. Registry IDs reference the logical
entities above. Checksums, bytes and profile definitions live in the asset
registry; agents and reference labels are deliberately separate.

```json
{
  "schema": "phdsim-observation-v2-draft",
  "observation_id": "example@r1/drive-a/camera-front/0042",
  "dataset_id": "example",
  "release_id": "r1",
  "sequence_id": "drive-a",
  "stream_id": "rig-a/camera-front/native",
  "source_frame_id": "0042",
  "source_ordinal": 42,
  "time": {
    "source_value": "4200000",
    "source_unit": "us",
    "kind": "capture",
    "clock_id": "example@r1/recording-clock",
    "timestamp_ns": 4200000000,
    "interval_start_ns": null,
    "interval_end_ns": null,
    "precision_ns": null
  },
  "asset_ids": ["example@r1/assets/rgb-0042"],
  "geometry_ref": "example@r1/geometry/rig-a",
  "provenance_ref": "example@r1/import-01"
}
```

```json
{
  "association_id": "example@r1/associations/0042",
  "anchor_observation_id": "example@r1/drive-a/camera-front/0042",
  "member_observation_ids": [
    "example@r1/drive-a/camera-front/0042",
    "example@r1/drive-a/thermal-front/0039"
  ],
  "temporal": {
    "relation": "approximate",
    "method": "nearest_source_timestamp",
    "tolerance_ns": 40000000,
    "member_offsets_ns": [0, -12000000]
  },
  "spatial": {
    "relation": "calibrated_views",
    "pixel_aligned": false,
    "geometry_ref": "example@r1/geometry/rig-a"
  }
}
```

The association example preserves a 12 ms difference and does not imply identical
pixels. An availability rule must still check whether both measurements can be
used at a particular decision time. For PST900, unknown physical times remain
null and pairing is attributed to the provided dataset, not an invented clock.

## Storage and the role of a database

Recommended starting architecture:

| Layer | Proposed storage | Reason |
|---|---|---|
| Original and prepared binary data | Immutable files on project storage or private S3 objects | Preserve original encodings; access through a storage resolver, not absolute Windows paths. |
| Observation and relation catalog | Versioned Parquet tables | Typed, portable, partitionable metadata shared by batch jobs. Small development exports can remain JSONL with the same logical schema. |
| Interactive analysis | DuckDB over published Parquet snapshots | SQL filtering and joins without deploying a server. DuckDB can query multiple Parquet files and push filters into scans. |
| Temporary decoding, conversion and training | Per-job scratch/local working data | Reproducible working copies and model-specific caches. |
| Optional future shared application | PostgreSQL metadata catalog on an allocated service/VM | Useful if multiple users need transactional edits, job tracking or an API. Payload bytes still live in the data store. |

This is an architectural recommendation, not an installed database or a measured
I/O benchmark. It follows [DuckDB's Parquet support](https://duckdb.org/docs/current/data/parquet/overview).
Use independent Parquet outputs per worker and one publication/validation step.
Do not let Slurm jobs concurrently mutate one shared embedded `.duckdb` file:
the in-process write model and shared-filesystem locking require different
coordination. A server/catalog design is a later option if concurrent updates
become necessary. [DuckDB concurrency documentation](https://duckdb.org/docs/current/connect/concurrency)

Store logical asset IDs and root-relative keys. Deployment configuration resolves
them to a local project directory or S3 endpoint/bucket. Credentials and signed
download URLs stay out of public manifests. A packaged asset may have a typed
member/message selector; a byte offset is only valid when the encoding/container
and its index actually support that access. Distinguish container checksums from
decoded/member checksums.

At scale, group related samples into moderately sized shards when benchmarks
show that individual-file access is a bottleneck. Choose shard size and optional
array storage after measuring representative image, radar and event workloads.
Do not expand every encoded measurement into a generic PNG or float tensor, and
do not partition metadata into one file per observation.

### Cyfronet execution and retention

Cyfronet documents both project storage and S3-compatible Object Storage. Use
allocated persistent project/S3 storage for published releases and run conversion
as batch CPU jobs; neural training can use an appropriate GPU allocation.
Per-sequence or per-source-package jobs can run independently and resume after
failure. No cluster, quota, account, bucket or grant is assumed to exist yet.
[Cyfronet storage resources](https://www.cyfronet.pl/en/supercomputers/our-supercomputers),
[Object Storage offering](https://www.cyfronet.pl/pl/offer/cloud-computing)

Scratch is temporary. The published Helios documentation states automatic
deletion of old scratch data after 30 days and job directories after 7 days.
Check the chosen machine's current rules and allocated quota; scratch is not
the sole repository for completed imports. Heavy transfers and conversion run
on allocated nodes rather than the login host.
[Helios documentation](https://docs.hpc.cyfronet.pl/supercomputers/helios/),
[general execution rules](https://docs.hpc.cyfronet.pl/environment/general-rules/)

Suggested publication flow:

```text
source release -> resumable download -> checksum/index validation
               -> parallel adapter jobs in temporary output prefixes
               -> schema/geometry/time/annotation validation
               -> immutable catalog + asset inventory + completion manifest
               -> experiment selection -> agent/tick allocation
```

Each job writes its own outputs. A coordinator verifies all declared parts,
checks counts and referential integrity, and publishes a versioned completion
manifest last. Object stores do not share POSIX rename semantics. Consumers open
only completed releases; an interrupted run does not silently become a dataset.

## Minimal implementation sequence

1. Finalize the common core and image/point/event/range payload profiles using
   the gaps above. Specify referential integrity, timestamp semantics, typed
   annotations, geometry and versioning before adopting a storage backend.
2. Migrate PST900 into an experimental v2 reader/writer while keeping v1
   experiments and historical outputs reproducible. Keep old fingerprints and
   new manifest identity separately; a schema migration changes metadata bytes.
3. Import a small Caltech sample to test thermal precision, partial pairs and
   multiple split sets; a Boreas sample to test asynchronous times/poses; and a
   DAIR-V2X sample to test physical sources and annotation coordinate frames.
   Add an event-window case from M2DGR or MUSES. Select native files, not only
   rendered preview images.
4. Add a Parquet export/storage resolver and benchmark metadata lookup plus
   payload reads. Decide any further packing from these measurements.
5. Prepare resumable CPU conversion jobs for the actual Cyfronet allocation,
   then expand coverage dataset by dataset. Add task models and fusion only
   after declaring each imported task profile.

Acceptance examples must cover different native times, unknown clocks, recorded
arrival time, missing/withheld labels, multiple official split sets, per-view and
global annotations, event intervals, radar/point channel units, duplicate
representations, shared bytes with distinct observation identities, Linux/S3
path resolution and interrupted publication. Strict validation remains in the
core; dataset-specific extensions must be namespaced and versioned rather than
accepted as arbitrary unvalidated fields.

A common observation format makes datasets loadable through one interface. It
does not make localization, forecasting and segmentation interchangeable tasks,
nor make the existing PSTNet fusion model applicable to arbitrary sensor views.
