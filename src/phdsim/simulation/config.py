"""Composition and validation of a synthetic mission scenario."""

from dataclasses import asdict, dataclass
import math
from phdsim.agents.rover import RoverConfig
from phdsim.agents.drone import DroneConfig
from phdsim.environments.grid import WorldConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.planning.grid import PlanningConfig
from phdsim.decision.acquisition.config import AcquisitionConfig

@dataclass(frozen=True)
class MissionConfig:
    time_budget: int = 100
    energy_budget: float = 150.0

@dataclass(frozen=True)
class Config:
    experiment: str = "scout_pilot_v0"
    seed: int = 42
    world: WorldConfig = WorldConfig()
    rover: RoverConfig = RoverConfig()
    drone: DroneConfig = DroneConfig()
    communication: CommunicationConfig = CommunicationConfig()
    mission: MissionConfig = MissionConfig()
    planning: PlanningConfig = PlanningConfig()
    acquisition: AcquisitionConfig = AcquisitionConfig()
    policy: str = "no_scouting"

    def __post_init__(self):
        w, h = self.world.size
        integer_fields = {
            "width": w, "height": h, "seed": self.seed,
            "rover sensor radius": self.rover.sensor_radius,
            "drone sensor radius": self.drone.sensor_radius,
            "measurement ticks": self.drone.measurement_ticks,
            "time budget": self.mission.time_budget,
            "bytes per cell": self.communication.bytes_per_cell,
            "lookahead": self.acquisition.lookahead,
            "cooldown ticks": self.acquisition.cooldown_ticks,
            "max requests": self.acquisition.max_requests,
            "minimum delay": self.communication.delivery_delay[0],
            "maximum delay": self.communication.delivery_delay[1],
        }
        if any(type(v) is not int for v in integer_fields.values()):
            raise ValueError("Grid sizes, seed, radii, counts and ticks must be integers")
        if w < 20 or h < 20:
            raise ValueError("alternative_corridors needs width and height >= 20")
        if self.world.generator != "alternative_corridors" or self.world.initial_map != "uncertain":
            raise ValueError("Supported world: alternative_corridors with initial_map=uncertain")
        if self.policy not in ("no_scouting", "uncertainty_scouting"):
            raise ValueError(f"Unknown policy: {self.policy}")
        for name, value in (("rover speed", self.rover.speed), ("drone speed", self.drone.speed),
                            ("energy budget", self.mission.energy_budget)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        costs = (self.rover.move_energy, self.drone.move_energy,
                 self.drone.measurement_energy, self.communication.energy_per_byte,
                 self.planning.risk_weight)
        if any(not math.isfinite(v) or v < 0 for v in costs):
            raise ValueError("Costs and risk weight must be finite and nonnegative")
        if self.mission.time_budget <= 0 or self.drone.measurement_ticks < 1:
            raise ValueError("Time budget and measurement duration must be positive")
        if min(self.rover.sensor_radius, self.drone.sensor_radius, self.acquisition.max_requests,
               self.acquisition.cooldown_ticks, self.communication.bytes_per_cell) < 0:
            raise ValueError("Radii, counts, cooldown and bytes must be nonnegative")
        if self.acquisition.lookahead < 1:
            raise ValueError("lookahead must be positive")
        lo, hi = self.communication.delivery_delay
        if lo < 1 or hi < lo:
            raise ValueError("delivery_delay must be ordered positive integer ticks")
        for value in (self.rover.sensor_accuracy, self.drone.sensor_accuracy):
            if not 0.5 < value < 1:
                raise ValueError("Sensor accuracy must be strictly between 0.5 and 1")
        if not 0.5 < self.planning.blocked_threshold < 1:
            raise ValueError("blocked_threshold must be between 0.5 and 1")
        if not 0 <= self.acquisition.entropy_threshold <= 1:
            raise ValueError("Entropy threshold must be in [0, 1] bits")

    def to_dict(self):
        data = asdict(self)
        data["agents"] = {"rover": data.pop("rover"), "drone": data.pop("drone")}
        return data
