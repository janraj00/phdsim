"""Allocate existing pool observations without retiming or changing payloads."""

from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import json
from phdsim.artifacts import write_json
from .pool import ObservationPool

SCHEDULE_SCHEMA = 'phdsim-schedule-v1'


@dataclass(frozen=True)
class AgentSlot:
    agent_id: str
    modality: str
    limit: int | None = 100
    stream_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.agent_id, str) or not self.agent_id or (not isinstance(self.modality, str)) or (not self.modality):
            raise ValueError('Agent id and its one own modality are required')
        if self.limit is not None and (type(self.limit) is not int or self.limit < 0):
            raise ValueError('Agent observation limit must be a nonnegative integer')
        if len(set(self.stream_ids)) != len(self.stream_ids):
            raise ValueError('Duplicate stream filter')


@dataclass(frozen=True)
class Assignment:
    sequence_id: str
    tick: int
    agent_id: str
    observation_id: str


@dataclass(frozen=True)
class Schedule:
    pool_fingerprint: str
    agents: tuple[AgentSlot, ...]
    split: str
    mode: str
    assignments: tuple[Assignment, ...]
    unassigned_observation_ids: tuple[str, ...]

    def validate(self, pool: ObservationPool) -> None:
        if self.pool_fingerprint != pool.fingerprint:
            raise ValueError('Schedule belongs to a different observation pool')
        if self.split not in ('train', 'validation', 'test') or self.mode not in ('partition', 'replicate'):
            raise ValueError('Unknown schedule split or allocation mode')
        agents = {a.agent_id: a for a in self.agents}
        if not agents or len(agents) != len(self.agents):
            raise ValueError('Agent ids must be unique and nonempty')
        counts, slots, owned = (Counter(), set(), set())
        for item in self.assignments:
            if item.agent_id not in agents or item.observation_id not in pool.by_id:
                raise ValueError('Assignment references an unknown agent or observation')
            agent = agents[item.agent_id]
            row = pool.by_id[item.observation_id]
            if (item.sequence_id, item.tick) != row.frame or row.split != self.split:
                raise ValueError('Assignment must preserve original frame and split')
            if row.modality != agent.modality or (agent.stream_ids and row.stream_id not in agent.stream_ids):
                raise ValueError("Observation does not match the agent's one own modality/stream filter")
            slot = (item.sequence_id, item.tick, item.agent_id)
            if slot in slots:
                raise ValueError('Agent can receive at most one own observation per frame')
            if self.mode == 'partition' and item.observation_id in owned:
                raise ValueError('Partition must not replicate observations')
            slots.add(slot)
            owned.add(item.observation_id)
            counts[item.agent_id] += 1
            if agent.limit is not None and counts[item.agent_id] > agent.limit:
                raise ValueError('Assignment exceeds agent observation limit')
        expected = {r.observation_id for r in pool.records if r.split == self.split} - owned
        if len(set(self.unassigned_observation_ids)) != len(self.unassigned_observation_ids) or set(self.unassigned_observation_ids) != expected:
            raise ValueError('Unassigned observation audit does not match allocation')

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        if destination.exists():
            raise FileExistsError(f'Schedule already exists: {destination}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, {'schema': SCHEDULE_SCHEMA, **asdict(self)})

    @classmethod
    def load(cls, path: str | Path, pool: ObservationPool) -> 'Schedule':
        row = json.loads(Path(path).read_text(encoding='utf-8'))
        if row.pop('schema') != SCHEDULE_SCHEMA:
            raise ValueError('Unsupported schedule schema')
        row['agents'] = tuple((AgentSlot(**{**a, 'stream_ids': tuple(a.get('stream_ids', ()))}) for a in row['agents']))
        row['assignments'] = tuple((Assignment(**a) for a in row['assignments']))
        row['unassigned_observation_ids'] = tuple(row['unassigned_observation_ids'])
        result = cls(**row)
        result.validate(pool)
        return result


def allocate(pool: ObservationPool, agents: tuple[AgentSlot, ...], *, split: str='test', mode: str='partition') -> Schedule:
    if not agents or len({a.agent_id for a in agents}) != len(agents):
        raise ValueError('Agent ids must be unique and nonempty')
    if split not in ('train', 'validation', 'test') or mode not in ('partition', 'replicate'):
        raise ValueError('Unknown schedule split or allocation mode')
    modalities = {r.modality for r in pool.records}
    streams = {r.stream_id: r.modality for r in pool.records}
    for agent in agents:
        if agent.modality not in modalities or any((streams.get(s) != agent.modality for s in agent.stream_ids)):
            raise ValueError('Agent references an unknown modality or stream')
    counts, slots, assignments = (Counter(), set(), [])
    rows = sorted((r for r in pool.records if r.split == split), key=lambda r: (r.sequence_id, r.tick, r.modality, r.stream_id, r.observation_id))
    if not rows:
        raise ValueError('Selected split contains no observations')
    for row in rows:
        candidates = [a for a in agents if a.modality == row.modality and (not a.stream_ids or row.stream_id in a.stream_ids) and (a.limit is None or counts[a.agent_id] < a.limit) and ((*row.frame, a.agent_id) not in slots)]
        if mode == 'partition':
            candidates = sorted(candidates, key=lambda a: (counts[a.agent_id], agents.index(a)))[:1]
        for agent in candidates:
            assignments.append(Assignment(*row.frame, agent.agent_id, row.observation_id))
            counts[agent.agent_id] += 1
            slots.add((*row.frame, agent.agent_id))
    owned = {a.observation_id for a in assignments}
    schedule = Schedule(pool.fingerprint, agents, split, mode, tuple(assignments), tuple((r.observation_id for r in rows if r.observation_id not in owned)))
    schedule.validate(pool)
    return schedule
