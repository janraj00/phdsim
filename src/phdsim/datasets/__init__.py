"""Shared dataset packages and allocation; dataset adapters live in named subpackages."""

from .allocation import AgentSlot, Assignment, Schedule, allocate
from phdsim.artifacts import digest, read_lines, write_json, write_lines
from .pool import ObservationPool, PoolRecord, pool_fingerprint, prepare_pool, validate_records
