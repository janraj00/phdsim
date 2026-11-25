"""Read the JSON experiment configuration without importing any model stack."""

import json
from pathlib import Path
from phdsim.simulation.config import Config, MissionConfig
from phdsim.agents.rover import RoverConfig
from phdsim.agents.drone import DroneConfig
from phdsim.environments.grid import WorldConfig
from phdsim.communication.delayed import CommunicationConfig
from phdsim.planning.grid import PlanningConfig
from phdsim.decision.acquisition.config import AcquisitionConfig

def load_config(path: str | Path) -> Config:
    data = json.loads(Path(path).read_text())
    agents = data.pop("agents", {})
    if set(agents) - {"rover", "drone"}:
        raise ValueError("Unknown agent in configuration")
    for key, cls in (("world", WorldConfig), ("communication", CommunicationConfig),
                     ("mission", MissionConfig), ("planning", PlanningConfig),
                     ("acquisition", AcquisitionConfig)):
        values = data.get(key, {})
        for field in ("size", "delivery_delay"):
            if field in values:
                values[field] = tuple(values[field])
        data[key] = cls(**values)
    data["rover"] = RoverConfig(**agents.get("rover", {}))
    data["drone"] = DroneConfig(**agents.get("drone", {}))
    return Config(**data)
