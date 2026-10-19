"Replay current-frame originals and pull a neighbor's observation on demand."
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace

from phdsim.costs import CostLedger
from phdsim.decision import Policy, choose_action
from phdsim.fusion import Fusion
from phdsim.evaluation.presence import Evaluator
from phdsim.perception import Perception
from phdsim.datasets import ObservationPool, PoolRecord, Schedule
from phdsim.decision.actions import Acquire, ActionEstimate, Stop
from phdsim.costs.types import CostComponent, CostVector
from phdsim.decision.view import DecisionView
from phdsim.datasets.observations import Observation
from phdsim.core.identity import stable_id

def transfer_cost(byte_count: int=0) -> CostVector:
    return CostVector((CostComponent('transfers', 'transfer', 1), CostComponent('bytes', 'byte', byte_count), CostComponent('initial_sensing', 'observation', None, 'excluded'), CostComponent('processing', 'operation', None, 'excluded'), CostComponent('time', 's', None, 'unmeasured')))

class ReplayEngine:

    def __init__(self, pool: ObservationPool, schedule: Schedule, perception: Perception, fusion: Fusion, evaluator: Evaluator, loader: Callable[[PoolRecord], Observation], neighbors: dict[str, tuple[str, ...]] | None=None):
        schedule.validate(pool)
        self._pool, self._schedule = (pool, schedule)
        self._perception, self._fusion, self._evaluator, self._loader = (perception, fusion, evaluator, loader)
        agents = {a.agent_id for a in schedule.agents}
        self._neighbors = {a: tuple(sorted(agents - {a})) for a in agents} if neighbors is None else dict(neighbors)
        if set(self._neighbors) != agents or any((a in peers or len(set(peers)) != len(peers) or (not set(peers) <= agents) for a, peers in self._neighbors.items())):
            raise ValueError('Neighbor graph must reference known, distinct agents')
        assigned_ids = {a.observation_id for a in schedule.assignments}
        if any((r.modality not in perception.supported_modalities for r in pool.records if r.observation_id in assigned_ids)):
            raise ValueError('Task perception cannot process an allocated modality')

    def run(self, policy: Policy, ledger: CostLedger, emit: Callable[[str, dict], None]) -> tuple[dict, ...]:
        frames = defaultdict(list)
        for item in self._schedule.assignments:
            frames[item.sequence_id, item.tick].append(item)
        configs = {a.agent_id: a for a in self._schedule.agents}
        outcomes = []
        for frame, assignments in sorted(frames.items()):
            rows = {item.agent_id: self._pool.by_id[item.observation_id] for item in assignments}
            originals = {}
            for owner, row in rows.items():
                observation = self._loader(row)
                if (observation.observation_id, observation.target, observation.modality, observation.source_id) != (row.observation_id, row.target, row.modality, row.stream_id):
                    raise ValueError('Loader returned a different observation')
                originals[owner] = observation
                emit('deliveries', {'phase': 'own', 'frame': frame, 'receiver': owner, 'observation': observation})
            for receiver in sorted(originals):
                own = originals[receiver]
                known = {own.observation_id: own}
                result = self._fusion.update(None, self._perception.process(own))
                if result.target != own.target or result.observation_ids != (own.observation_id,):
                    raise ValueError('Task processing returned a different target or own evidence')
                initial = result
                attempted, received, received_bytes = (set(), [], 0)
                while True:
                    candidates = []
                    blocked = False
                    for owner in self._neighbors[receiver]:
                        if owner not in originals:
                            continue
                        row, observation = (rows[owner], originals[owner])
                        if observation.target != own.target or observation.observation_id in known:
                            continue
                        action = Acquire(stable_id('pull', receiver, owner, *map(str, frame), row.observation_id), receiver, owner, own.target, row.modality, (('observation_id', row.observation_id),))
                        if action.key in attempted:
                            continue
                        cost = transfer_cost(self._pool.payload_path(row).stat().st_size)
                        if ledger.refusal_reason(cost) is None:
                            candidates.append(ActionEstimate(action, cost, cost_model_version='stored-payload-transfer-v1'))
                        else:
                            blocked = True
                    reason = ('budget_blocked' if blocked else 'no_available_neighbor_observation') if not candidates else None
                    view = DecisionView(receiver, own.target, result, tuple((o.reference() for o in known.values())), tuple(sorted(attempted)), (configs[receiver].modality,), self._neighbors[receiver], ledger.remaining(), reason)
                    if hasattr(policy, 'estimate'):
                        candidates = [replace(c, predicted_gain=estimate[0], gain_model_version=policy.version)
                                      if (estimate := policy.estimate(view, c)) is not None else c for c in candidates]
                    choice = choose_action(policy, view, tuple(candidates))
                    emit('decisions', {'frame': frame, 'view': view, 'candidates': candidates, 'choice': choice})
                    if isinstance(choice, Stop):
                        break
                    selected = next((c for c in candidates if c.action == choice))
                    attempted.add(choice.key)
                    incoming = originals[choice.source_id]
                    before = result
                    execution_id = stable_id('transfer', policy.name, choice.action_id)
                    ledger.charge(execution_id, selected.cost)
                    received.append(incoming.observation_id)
                    received_bytes += int(selected.cost.get('bytes').value)
                    emit('transfers', {'execution_id': execution_id, 'frame': frame, 'sender': choice.source_id, 'receiver': receiver, 'observation': incoming, 'estimated_cost': selected.cost, 'settled_cost': selected.cost, 'status': 'success'})
                    emit('deliveries', {'phase': 'neighbor', 'frame': frame, 'receiver': receiver, 'sender': choice.source_id, 'observation': incoming})
                    result = self._fusion.update(result, self._perception.process(incoming))
                    if result.target != own.target or set(result.observation_ids) != {*known, incoming.observation_id}:
                        raise ValueError('Task fusion returned a different target or evidence set')
                    known[incoming.observation_id] = incoming
                    emit('experiences', {'execution_id': execution_id, 'context_before': view, 'action': choice, 'result_after': result, 'quality': self._evaluator.evaluate(own.target, before, result), 'estimated_cost': selected.cost, 'settled_cost': selected.cost, 'split': self._schedule.split, 'policy': policy.name})
                quality = self._evaluator.evaluate(own.target, initial, result)
                outcomes.append({'frame': frame, 'agent_id': receiver, 'own_modality': configs[receiver].modality, 'target': own.target, 'own_observation_id': own.observation_id, 'received_observation_ids': tuple(received), 'initial_result': initial, 'final_result': result, 'quality': quality, 'transfers': len(received), 'bytes': received_bytes, 'stop_reason': choice.reason})
        return tuple(outcomes)
