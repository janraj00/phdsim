"""Link delay and observation payload accounting, separate from sensing."""

from dataclasses import dataclass
from phdsim.core.randomness import keyed_rng

@dataclass(frozen=True)
class CommunicationConfig:
    delivery_delay: tuple[int, int] = (1, 5)
    bytes_per_cell: int = 8
    energy_per_byte: float = 0.0005


@dataclass(frozen=True)
class DelayedLink:
    config: CommunicationConfig
    seed: int

    def delay(self, request_id: int) -> int:
        return keyed_rng(self.seed, "link", request_id).randint(*self.config.delivery_delay)

    def payload_bytes(self, cell_count: int) -> int:
        return cell_count * self.config.bytes_per_cell
