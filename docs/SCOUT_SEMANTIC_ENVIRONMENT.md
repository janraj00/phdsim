# SCOUT semantic terrain experiment

Design proposal, 2026-11-20. The task is to produce a semantic terrain map
for a specified region, class set and quality requirement, with time, energy
and communication constraints. The existing elevation experiment provides a
replay and scheduling reference. The semantic fixed sweep already runs in
`phdsim.experiments.scout.semantic_mission`.

## First scene

Generate a small terrestrial test plot with patches of exposed soil, rock and
low vegetation. A low vegetation patch and a bare patch can have similar RGB
appearance. The vegetation adds surface structure that simulated LiDAR samples
can help resolve. A different patch can have distinctive RGB appearance and
nearly flat geometry. Include easy patches and patches where both channels
remain ambiguous. This produces cases where one channel is sufficient, where
fusion helps and where more evidence is needed.

Begin with two drones and one rover as a proposed implementation default.
Use overlapping capability sets: one RGB drone, one drone with RGB and LiDAR,
and one rover with a local LiDAR view. Capture paired RGB and LiDAR at scripted
common poses for the initial sensor test. The complete fleet composition can
later change in configuration. Add thermal sensing when a scene can supply
an apparent temperature field at capture time with a defined relation to the
classes or another required map layer.

## Modules and interfaces

| Module | Input | Output |
|---|---|---|
| Environment generator | Seed, spatial resolution, patch statistics, geometry and material parameters | Reference class grid and physical fields. Ground and surface elevation, visible reflectance and spatial structure belong to the simulator. |
| Sensor model | Physical fields, sensor pose and configuration, capture time | Timestamped noisy observations with spatial support, validity, sensor ID and observation ID. |
| Perception and fusion | Available observations, registration and model | Class probabilities by cell and evidence provenance. |
| Agent and motion | Starting pose, sensor inventory, motion profile, availability and resources | Feasible observation options with capture pose, duration and resource estimates. |
| Coverage planner | Known region and prior map, configured sensor support and motion costs | A preplanned schedule for visiting measurement poses. |
| SCOUT acquisition | Current map estimates, pending work, received messages and feasible options | Use existing evidence, request evidence, schedule a new observation, or continue. |
| Communication | Serialized message, destination, link conditions | Delivery event and recorded bytes and timing. |
| Offline evaluation | Map estimates, reference class grid and mission trace | Coverage, semantic accuracy by class, time, energy, traffic and correctness of stopping. |

Use a 2D grid for class estimates and height fields for terrain and visible
surface. Grid coordinates and metres per cell are part of the scene model.
The first benchmark has a known shared frame and accurate poses. Later scenes
may supply full 3D geometry through the same sensor interfaces. A switch of
scene profile changes the generated fields and available cues. A lunar profile
would separately change light, temperature and robot mobility assumptions.

Configure the class set, class model, region, quality targets and budgets per
task. The world and sensor models define evidence. The planner reads class
estimates and expected improvements. Class names and sensor modality names
have no special branches in the acquisition algorithm.

## Local development and HERCULES validation

Develop and compare SCOUT policies in the small seeded Python simulator.
Validate the same policies in HERCULES through its API. The semantic replay takes
registered `Capture` records from a supplied capture function. The synthetic
capture function has access to the simulated scene. Fusion receives only the
returned captures, and evaluation reads the reference classes separately.

For the adaptive loop, let the execution layer take a chosen agent, sensor and
measurement pose, then report completion or failure and any observations. Keep
the requested region separate from the pose. Preserve observation identity,
capture and delivery times, coordinate frame and cost accounting across both
simulators. The HERCULES adapter will translate the chosen action into API
commands and register sensor measurements onto the experiment grid. The first
integration check is one movement and one usable sensor capture, followed by a
short closed-loop mapping run.

Ares is a candidate for the HERCULES validation runs. Try one Slurm GPU job with
the simulator and Python client on the same compute node, communicating over
loopback. Verify that the packaged Unreal scene renders offscreen and returns
usable sensor frames on the allocated node before running batches. This setup
has yet to be tested. See [Ares](https://docs.hpc.cyfronet.pl/supercomputers/ares)
and [HERCULES Core APIs](https://lunarlab-gatech.github.io/HERCULES/apis/).

## Adaptive aerial altitude

```sh
PYTHONPATH=src python3 -m phdsim.experiments.scout.semantic_mission \
  --drone-altitudes 2 6 --drone-fov-deg 60 --cell-size-m 0.5 \
  --output runs/scout-semantic-x500
```

The flag enables the adaptive aerial reference policy. Each drone can choose
any cell centre and any configured altitude while retaining its existing
sensor package. With a square 60-degree field of view and 0.5 m cells, the
nominal footprints at 2 m and 6 m are 5 × 5 and 13 × 13 cells. Footprints count
cell centres inside the projection onto a flat reference plane and are clipped
at the plot boundary. The nominal support is shared by the RGB and LiDAR
models in a paired capture. The plot stays at 24 × 18 cells in the demo.
Both the fixed sweep and adaptive policy use `--drone-fov-deg` and `--cell-size-m`.
Changing the cell size changes the physical plot size. The rover retains its
5 × 5 cell footprint.

The reference policy ranks finer or newly sampled cells by Shannon entropy of
the class probabilities divided by the maximum entropy for that class count.
Cells without evidence have uncertainty 1. The policy discounts cells covered
by pending measurements and divides the score by estimated acquisition duration.
It tracks the finest aerial scale from valid
samples received so far. Altitude therefore changes field of view, flight
duration and the score for revisits. The aerial horizon is 21 model seconds.
The rover keeps its two scheduled captures. The summary counts candidate views
and executed captures. This uses gridded sensors and an uncalibrated semantic
classifier. The default command continues to run the fixed sweep.

## Fixed RGB sweep with selective LiDAR captures

```sh
PYTHONPATH=src python3 -m phdsim.experiments.scout.semantic_mission \
  --selective-rovers --output runs/scout-semantic-selective-rovers
```

Two identical RGB drones fly the fixed sweep. Two LiDAR rovers begin idle in
opposite corners. The central planner scores the same 5 × 5 measurement
sites used for a full ground sweep. It sums normalized RGB entropy for cells
with a delivered RGB estimate, entropy at least 0.6, and no LiDAR estimate or
pending ground coverage. The sum is divided by the rover's travel and capture
time. Only affordable proposals that complete by the deadline are considered.
Each site can be assigned once. The deadline is the later of the fixed flight
completion and a planned full ground sweep with those rovers.

The replay shows ground travel, capture times and fused map updates. The
summary reports whole-area RGB and fused accuracy over time and energy by
robot. Accuracies use the reference map offline. Planning uses the delivered
estimates and the known motion and sensor footprint models.

## X500 flight profile

Both semantic policies use the [Gazebo X500](https://docs.px4.io/v1.16/en/sim_gazebo_gz/index)
with [PX4 v1.16.0 airframe 4001](https://github.com/PX4/PX4-Autopilot/blob/v1.16.0/ROMFS/px4fmu_common/init.d-posix/airframes/4001_gz_x500)
as the reference. Each drone starts at 3 m by default and uses the same
kinematics with its own sensor inventory. The local trajectory is a
point-to-point approximation of the PX4 mission
[S-curve](https://docs.px4.io/v1.16/en/config_mc/mc_jerk_limited_type_trajectory).
Drones start at rest, travel on a straight 3D leg, brake to rest and then
measure. Horizontal and vertical motion use the same progress along the leg.

The cap values are the PX4
[controller defaults](https://docs.px4.io/v1.16/en/advanced_config/parameter_reference):
horizontal cruise 5 m/s (`MPC_XY_CRUISE`), climb 3 m/s
(`MPC_Z_V_AUTO_UP`), descent 1.5 m/s (`MPC_Z_V_AUTO_DN`), horizontal
acceleration 3 m/s² (`MPC_ACC_HOR`) and jerk 4 m/s³
(`MPC_JERK_AUTO`). Symmetric vertical acceleration and braking use the lower
of the 4 and 3 m/s² vertical acceleration parameters
(`MPC_ACC_UP_MAX`, `MPC_ACC_DOWN_MAX`). Each limit is projected onto the leg.

The clock samples the curve at one-second intervals. The scheduler rounds
flight time up to the next tick and allocates two further ticks for the
synthetic capture to become available. The replay includes per-tick poses,
continuous flight duration, tick of arrival, and tick of capture completion.
Energy uses the existing per-metre and per-capture synthetic charge.
The local model uses a flat vertical reference and omits terrain following,
collision checking along the leg, PX4 waypoint lookahead, closed-loop tracking
and airframe or payload dynamics.

## Observation and fusion experiment

1. Generate material patches and geometry from the same seeded scene. Add
   within-class variation in visible appearance and surface structure, and
   overlap between classes. Keep reference labels and generation state in the
   environment and offline evaluator.
2. Generate RGB patches with illumination, footprint, resolution and noise.
   Generate sparse geometric samples from the same physical scene for LiDAR,
   with range-dependent noise and invalid returns. Treat both observation
   models as synthetic approximations. Include explicit visibility and
   missing-data masks. Avoid a class-specific paint code or simulated sensors
   that simply return labels at different rates of accuracy.
3. Run RGB-only, LiDAR-only and paired fusion on the same poses and held-out
   scenes. A simple classifier on observed colour and local geometric features
   is sufficient initially. Use the same splits and scoring for all models.
   Compare performance for each class and on hard patches as well as the full
   map. Assign an observation ID at capture and count retransmissions of it
   once in fusion. Report whether shared errors are modeled.

Plot or save, for one reproducible run, the reference map, both observations,
the class map from each channel, and the fused class map. Save the seeds,
settings and runtime measurement trace. Validate that changing capture
conditions changes measurements while the semantic truth stays the same.
Use independent scene seeds for fitting, calibration and final evaluation.

## Coverage baseline

The first strong, reproducible fixed baseline for a rectangular plot uses
parallel strips. Generate horizontal and vertical sweeps, both starting ends,
and waypoint spacing from the declared sensor footprint. Sample at the same
allowed poses and with the same capture model as the adaptive policy. For two
drones, enumerate splits of the strips and assignments to the robots. Score
each plan by the time when the final assigned robot finishes, including travel
to the first pose, transitions and capture time. Reject plans beyond the
energy budgets. If full nominal coverage is infeasible, use the same budget
and select the largest nominal coverage, breaking ties by elapsed time.
Give the baseline access to the same feasible sensors and shared prior. When
including fixed rover checks or repeat observations, plan them with the
public prior, starting poses and resources. Keep that allocation fixed before
the run and compare under the same map quality and stopping rule.

This is an optimized schedule within a stated family of sweeps. For
irregular regions, known obstacles and larger fleets, consider cell
decomposition and route allocation before choosing a stronger comparator.
Compare the current expected-gain approach with both fixed coverage and a
simple adaptive alternative that prioritizes nearby uncertain regions. Match
observation models, constraints and stop decisions across policies. Distinguish
coverage of the surface by a sensor from verified quality of the class map.

Relevant established methods include [Choset's boustrophedon cell
decomposition](https://publications.ri.cmu.edu/storage/publications/pub_files/pub4/choset_howie_2000_3/choset_howie_2000_3.pdf),
[DARP for multi-robot coverage](https://kapoutsis.info/wp-content/uploads/2017/02/j3.pdf),
and [Datsko et al. for energy-aware multi-UAV coverage](https://doi.org/10.1109/LRA.2024.3358581).
These provide coverage comparators. The semantic experiment additionally
scores whether an observation resolves class ambiguity.

## Communication experiment

Use an immediate shared map in the first run so the effect of fusion and
measurement scheduling can be measured directly. Keep capture time, delivery
time, sender, sensor, receiver, observation ID and covered region in traces.
Once communication is enabled, each agent updates its local estimate only on
delivery. Include the encoded payload and message metadata in byte counts.
Separate observation packets and map updates from requests, offers and
acknowledgements. Measure bytes by message, link load per unit time, delays and
quality at mission completion. An initial comparison can keep the motion plan
fixed and vary only which already captured evidence is transmitted. Afterward,
allow measurement choices to respond to delayed or missing peer evidence.

## Implementation order

1. One reproducible RGB and LiDAR scene, with scripted poses and visible
   single-sensor and fused maps. Verify reference-data boundaries and sensor
   dependence on capture conditions before layering on autonomous decisions.
2. Connect a two-drone and rover schedule to the same scene. Run the optimized
   sweep and adaptive policies using matched settings. Report class quality,
   verified completion, unresolved coverage, time and energy.
3. Enable delayed messages and a serialized byte budget. Compare sending all
   evidence with selective transmission and measure the quality–traffic tradeoff.
