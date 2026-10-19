"""Follow one existing test frame through the actual frozen presence classifiers."""

from dataclasses import replace

from .trace import CallTrace


def run_presence(pool_path, schedule_path, model_directory):
    from phdsim.costs import CostLedger
    from phdsim.costs.types import CostComponent, CostVector
    from phdsim.datasets import ObservationPool, Schedule
    from phdsim.decision import AlwaysAcquire, NoAcquisition, UncertaintyThreshold, choose_action
    from phdsim.evaluation.presence import BrierEvaluator
    from phdsim.fusion import MeanProbabilityFusion
    from phdsim.perception import load_observation
    from phdsim.perception.cnn_training import load_cnn
    from phdsim.perception.cnn_perception import CnnPerception
    from phdsim.perception.cnn_input import image_tensor
    from phdsim.perception.resnet18_model import ResNet18Model
    from phdsim.runtime.presence import ReplayEngine, transfer_cost

    pool = ObservationPool(pool_path)
    schedule = Schedule.load(schedule_path, pool)
    frame = min((a.sequence_id, a.tick) for a in schedule.assignments)
    assignments = tuple(a for a in schedule.assignments if (a.sequence_id, a.tick) == frame)
    owned = {a.observation_id for a in assignments}
    schedule = replace(schedule, assignments=assignments,
                       unassigned_observation_ids=tuple(r.observation_id for r in pool.records
                                                        if r.split == schedule.split and r.observation_id not in owned))
    schedule.validate(pool)
    scenarios = []
    for policy in (NoAcquisition(), AlwaysAcquire(), UncertaintyThreshold()):
        trace = CallTrace()
        for function, explanation in (
            (load_cnn, 'Odczyt zamrożonych wag i kontrola zgodności z pulą'),
            (ReplayEngine.__init__, 'Sprawdzenie przydziału i grafu sąsiedztwa'),
            (ReplayEngine.run, 'Pętla po klatkach i agentach'),
            (load_observation, 'Dostarczenie obserwacji i sprawdzenie SHA256 PNG'),
            (CnnPerception.process, 'Percepcja dostarczonego obrazu; możliwy odczyt z cache'),
            (image_tensor, 'Cały obraz do tensora 3×216×384'),
            (ResNet18Model.forward, 'Sieć modalności zwraca logit obecności'),
            (MeanProbabilityFusion.update, 'Pierwsza prognoza albo średnia dostarczonych prognoz'),
            (choose_action, 'Wywołanie polityki i kontrola legalności akcji'),
            (type(policy).choose, 'Reguła wybranej strategii pobierania'),
            (CostLedger.refusal_reason, 'Czy budżet dopuszcza ten transfer?'),
            (CostLedger.charge, 'Naliczenie wykonanego transferu'),
            (BrierEvaluator.evaluate, 'Ocena offline; wynik nie wraca do polityki'),
        ):
            trace.watch(function, explanation)

        def emit(kind, row):
            if kind == 'decisions':
                view, choice = row['view'], row['choice']
                details = {'agent': view.receiver_id, 'p': view.result.prediction,
                           'entropy': view.result.uncertainty, 'candidates': len(row['candidates']),
                           'choice': type(choice).__name__, 'reason': getattr(choice, 'reason', None)}
            elif kind in ('deliveries', 'transfers'):
                details = {'phase': row.get('phase', 'transfer'), 'receiver': row['receiver'],
                           'observation': row['observation'].observation_id,
                           'modality': row['observation'].modality}
            else:
                details = {'gain': row['quality'].gain}
            trace.event(kind, details)

        with trace:
            trained = load_cnn(pool, model_directory)
            engine = ReplayEngine(pool, schedule, trained.perception, MeanProbabilityFusion(),
                                  BrierEvaluator(pool.read_labels()), lambda row: load_observation(pool, row))
            ledger = CostLedger(CostVector((CostComponent('transfers', 'transfer', len(assignments)),)), transfer_cost())
            results = engine.run(policy, ledger, emit)
        summary = {'frame': frame, 'policy': policy.name,
                   'agents': [{'agent': r['agent_id'], 'p_before': r['initial_result'].prediction,
                               'p_after': r['final_result'].prediction, 'pulls': r['transfers'],
                               'stop_reason': r['stop_reason']} for r in results]}
        scenarios.append({'title': 'Presence: ' + policy.name,
                          'intro': 'Jedna rzeczywista klatka ze starego testu, istniejące wytrenowane modele RGB i thermal. '
                                   'To pokazanie wykonania na pojedynczej klatce. Każda strategia zaczyna z nową instancją modeli i pustym cache.',
                          'steps': trace.rows, 'summary': summary})
    return scenarios
