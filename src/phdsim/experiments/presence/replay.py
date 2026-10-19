'Compare decisions on the same fixed allocation and frozen perception models.'
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from hashlib import sha256
import csv
import json

from phdsim.costs import CostLedger
from phdsim.decision import DecisionConfig
from phdsim.fusion import FusionConfig
from phdsim.evaluation.presence import BrierEvaluator
from phdsim.perception import FitConfig, TrainingResult, load_observation, train_pool
from phdsim.datasets import ObservationPool, Schedule, write_json
from phdsim.costs.types import CostComponent, CostVector
from phdsim.serialization import jsonable
from phdsim.runtime.presence import ReplayEngine, transfer_cost

@dataclass(frozen=True)
class ProcessingConfig:
    fusion: FusionConfig
    decisions: tuple[DecisionConfig, ...]

    def __post_init__(self):
        if not self.decisions or len({c.key for c in self.decisions}) != len(self.decisions):
            raise ValueError('Choose at least one decision method, without duplicate names')

    @classmethod
    def defaults(cls, threshold: float=0.85) -> 'ProcessingConfig':
        return cls(FusionConfig(), (DecisionConfig('no_acquisition'), DecisionConfig('always_acquire'), DecisionConfig('uncertainty_threshold', threshold)))

    @classmethod
    def load(cls, path: str | Path) -> 'ProcessingConfig':
        row = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if set(row) != {'fusion', 'decisions'}:
            raise ValueError('Processing configuration requires separate fusion and decisions sections')
        return cls(FusionConfig(**row['fusion']), tuple((DecisionConfig(**item) for item in row['decisions'])))

def _mean(values):
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def evaluation_fingerprint(pool, schedule):
    labels = pool.read_labels()
    targets = sorted({pool.by_id[a.observation_id].target for a in schedule.assignments}, key=lambda t: (t.kind, t.id))
    return sha256(json.dumps([(t.kind, t.id, labels.get(t)) for t in targets], separators=(',', ':')).encode()).hexdigest()

def run_replay(pool: ObservationPool, schedule: Schedule, output: str | Path, *, threshold: float=0.85, transfer_budget: int | None=None, byte_budget: int | None=None, fit: FitConfig=FitConfig(), processing: ProcessingConfig | None=None, trained: TrainingResult | None=None, learned=None, trace: bool=True) -> dict:
    schedule.validate(pool)
    if schedule.split != 'test':
        raise ValueError('Evaluation replay requires a test schedule; training remains separate')
    for value in (transfer_budget, byte_budget):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('Budgets must be nonnegative integers')
    settings = processing if processing is not None else ProcessingConfig.defaults(threshold)
    if not schedule.assignments:
        raise ValueError('No observations were assigned')
    path = Path(output).resolve()
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f'Output directory is not empty: {path}')
    modalities = tuple(sorted({a.modality for a in schedule.agents}))
    provided_models = trained is not None
    trained = trained if provided_models else train_pool(pool, modalities, fit)
    perception = trained.perception
    if learned is not None:
        learned.validate(pool, trained, settings.fusion.method)
    fusion = settings.fusion.build(trained.class_prior, learned)
    evaluator = BrierEvaluator(pool.read_labels())
    engine = ReplayEngine(pool, schedule, perception, fusion, evaluator, lambda row: load_observation(pool, row))
    maximum = sum((len(schedule.agents) - 1 for _ in schedule.assignments))
    components = [CostComponent('transfers', 'transfer', maximum if transfer_budget is None else transfer_budget)]
    if byte_budget is not None:
        components.append(CostComponent('bytes', 'byte', byte_budget))
    budget = CostVector(tuple(components))
    policies = tuple((config.build(learned) for config in settings.decisions))
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / 'config.json', {'schema': 'phdsim-replay-experiment-v1', 'pool_fingerprint': pool.fingerprint, 'schedule': asdict(schedule), 'fit': asdict(fit), 'policies': [p.configuration() for p in policies], 'processing': asdict(settings), 'budget': jsonable(budget), 'task_adapter': pool.manifest.get('task', 'binary-classification-v1'), 'payload_scope': 'original stored payload, virtual delivery by file reference; no prediction broadcast', 'cost_scope': '1 transfer plus stored payload bytes; protocol overhead excluded; time unmeasured', 'fusion_assumption': 'conditional independence given class; paired training targets; train-only prior' if settings.fusion.method == 'independent_log_odds' else 'observation-weighted mean of delivered probability predictions', 'execution_order': 'sequence, tick, then agent id; all own observations delivered before any pulls', 'neighbors': 'complete static graph; only original own observations from the current frame', 'initial_sensing_and_processing_cost': 'excluded', 'collective_utility_learning': 'not_implemented'})
    if provided_models:
        snapshot = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        snapshot['fit'] = trained.model_snapshot['fit']
        snapshot['perception_training'] = 'loaded frozen CNN checkpoints; selected using validation only'
        write_json(path / 'config.json', snapshot)
    snapshot = json.loads((path / 'config.json').read_text(encoding='utf-8'))
    snapshot['evaluation_reference_sha256'] = evaluation_fingerprint(pool, schedule)
    snapshot['trace_enabled'] = trace
    write_json(path / 'config.json', snapshot)
    if learned is not None:
        snapshot = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        snapshot['acquisition_learning'] = learned.manifest
        snapshot['collective_utility_learning'] = f'offline expected reduction in {learned.gain_metric}; frozen before test'
        snapshot['fusion_assumption'] = ('regularized logistic model of paired CNN outputs; meta recording holdout'
                                         if settings.fusion.method == 'learned_probability' else
                                         snapshot['fusion_assumption'])
        write_json(path / 'config.json', snapshot)
    write_json(path / 'models.json', jsonable({'perception': trained.model_snapshot if provided_models else perception, 'fusion': fusion}))
    streams = ({kind: (path / f'{kind}.jsonl').open('w', encoding='utf-8', newline='\n')
                for kind in ('decisions', 'deliveries', 'transfers', 'experiences')} if trace else {})
    predictions, summaries, examples = ([], {}, {})
    labels = pool.read_labels()
    try:
        for policy in policies:
            ledger = CostLedger(budget, transfer_cost())

            def emit(kind, data):
                if kind in streams:
                    streams[kind].write(json.dumps(jsonable({'policy': policy.name, **data}), ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
            results = engine.run(policy, ledger, emit)
            summaries[policy.name] = {'agent_frames': len(results), 'accuracy': _mean((r['quality'].accuracy_after for r in results)), 'brier': _mean((r['quality'].after for r in results)), 'evaluated_agent_frames': sum((r['quality'].after is not None for r in results)), 'transfers': int(ledger.total.get('transfers').value), 'bytes': int(ledger.total.get('bytes').value)}
            if results:
                first_frame = results[0]['frame']
                examples[policy.name] = jsonable([r for r in results if r['frame'] == first_frame])
            for row in results:
                quality = row['quality']
                predictions.append({'policy': policy.name, 'sequence_id': row['frame'][0], 'tick': row['frame'][1], 'agent_id': row['agent_id'], 'own_modality': row['own_modality'], 'target_id': row['target'].id, 'reference_label': labels.get(row['target']), 'own_observation_id': row['own_observation_id'], 'received_observation_ids': json.dumps(row['received_observation_ids']), 'probability_before': row['initial_result'].prediction, 'probability_after': row['final_result'].prediction, 'brier_before': quality.before, 'brier_after': quality.after, 'gain': quality.gain, 'accuracy_after': quality.accuracy_after, 'transfers': row['transfers'], 'bytes': row['bytes'], 'stop_reason': row['stop_reason']})
    finally:
        for stream in streams.values():
            stream.close()
    with (path / 'predictions.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    counts = Counter((a.agent_id for a in schedule.assignments))
    split_records = [r for r in pool.records if r.split == schedule.split]
    summary = {'dataset_id': pool.manifest['dataset_id'], 'pool_observations': len(pool.records), 'test_pool_observations': len(split_records), 'assigned_observations': len(schedule.assignments), 'unassigned_test_observations': len(schedule.unassigned_observation_ids), 'per_agent': {a.agent_id: {'modality': a.modality, 'limit': a.limit, 'assigned': counts[a.agent_id]} for a in schedule.agents}, 'scheduled_frames': len({(a.sequence_id, a.tick) for a in schedule.assignments}), 'distinct_targets': len({pool.by_id[a.observation_id].target for a in schedule.assignments}), 'team_metric': 'mean individual quality over assigned agent-frames', 'policies': summaries}
    write_json(path / 'example.json', examples)
    targets = {pool.by_id[a.observation_id].target for a in schedule.assignments}
    reference = [labels[t] for t in targets if labels.get(t) in (0, 1)]
    prior = trained.class_prior
    summary['test_reference'] = {'positive': sum(reference), 'negative': len(reference) - sum(reference)}
    summary['training_prior_baseline'] = {
        'probability': prior,
        'accuracy': _mean(float(int(prior >= 0.5) == y) for y in reference),
        'brier': _mean((prior - y) ** 2 for y in reference),
    }
    for policy_name, item in summaries.items():
        item['per_agent'] = {}
        for agent in schedule.agents:
            selected = [p for p in predictions if p['policy'] == policy_name and p['agent_id'] == agent.agent_id]
            scored = [p for p in selected if p['reference_label'] in (0, 1)]
            tp = sum(p['probability_after'] >= 0.5 and p['reference_label'] == 1 for p in scored)
            tn = sum(p['probability_after'] < 0.5 and p['reference_label'] == 0 for p in scored)
            fp = sum(p['probability_after'] >= 0.5 and p['reference_label'] == 0 for p in scored)
            fn = sum(p['probability_after'] < 0.5 and p['reference_label'] == 1 for p in scored)
            recall = tp / (tp + fn) if tp + fn else None
            specificity = tn / (tn + fp) if tn + fp else None
            item['per_agent'][agent.agent_id] = {
                'accuracy': _mean(p['accuracy_after'] for p in selected),
                'brier': _mean(p['brier_after'] for p in selected),
                'transfers': sum(p['transfers'] for p in selected),
                'tp': tp, 'tn': tn, 'fp': fp, 'fn': fn,
                'recall': recall,
                'balanced_accuracy': (recall + specificity) / 2 if recall is not None and specificity is not None else None,
            }
    write_json(path / 'summary.json', summary)
    is_image = any(r.payload_format.endswith('png-v1') for r in pool.records)
    lines = ['# Pierwszy eksperyment na obserwacjach', '',
             'Zadanie: ' + pool.manifest.get('task', 'testowa klasyfikacja binarna') + '.', '',
             (('Dwa osobne ResNet-18: RGB i thermal; dostrojony ostatni blok i klasyfikator. '
               'Checkpointy wybrane na walidacji i zamrożone przed testem.' if provided_models else
               'Rzeczywiste obrazy PNG; prosty model logistyczny na cechach obrazu. ')
              + ' To kontrola działania przepływu, bez pełnej segmentacji i bez twierdzenia o przewadze metody.'
              if is_image else 'Syntetyczna kontrola regresji na skalarach.'), '',
             f'Fuzja: `{settings.fusion.method}`. Modele i ustawienia strategii są zamrożone przed oceną testową.', '',
             f'Przydzielono {len(schedule.assignments)} obserwacji w {summary["scheduled_frames"]} klatkach. '
             f'Etykiety klatek: {sum(reference)} dodatnich i {len(reference) - sum(reference)} ujemnych.', '',
             '| Agent | Modalność | Limit | Przydzielono |', '| --- | --- | ---: | ---: |']
    lines.extend(f'| {a.agent_id} | {a.modality} | {a.limit} | {counts[a.agent_id]} |' for a in schedule.agents)
    lines += ['', '| Strategia | Trafność | Brier ↓ | Pobrania | Bajty |', '| --- | ---: | ---: | ---: | ---: |']
    for name, row in summaries.items():
        accuracy = 'brak etykiet' if row['accuracy'] is None else f'{row["accuracy"]:.1%}'
        brier = 'brak etykiet' if row['brier'] is None else f'{row["brier"]:.4f}'
        lines.append(f'| {name} | {accuracy} | {brier} | {row["transfers"]} | {row["bytes"]} |')
    baseline = summary['training_prior_baseline']
    if reference:
        lines += ['', f'Stała prognoza z częstości klasy w treningu: trafność {baseline["accuracy"]:.1%}, '
                  f'Brier {baseline["brier"]:.4f}. Wyniki per agent i macierze pomyłek: `summary.json`.']
    lines += ['', ('CNN startują z wag ImageNet. Ostatni blok i klasyfikator są uczone wyłącznie na train; '
                   'walidacja wybiera checkpoint według Brier. Próg klasyfikacji wynosi 0,5; ustawienia strategii są zapisane w config.json.'
                   if provided_models else 'Modele i normalizacja są uczone wyłącznie na train. Validation pozostaje osobno; '
                   'w tym przebiegu nie stroimy na nim modelu ani progu. Test służy wyłącznie ocenie.'), '',
              'Agent zaczyna od własnej obserwacji. Może pobrać istniejący, oryginalny obraz sąsiada '
              'z tej samej klatki, po czym następuje percepcja i fuzja. Decyzja nie widzi etykiet ani obrazu sąsiada.', '',
              'Koszt: 1 transfer + dokładny rozmiar PNG w puli. Dostarczenie jest symulowane '
              'przez referencję do pliku; nie mierzymy fizycznej sieci. Narzut protokołu i przetwarzanie pomijamy.', '',
              'Klatki tego samego nagrania są skorelowane. Nie traktujemy ich jako niezależnych prób '
              'ani tego małego podzbioru jako wyniku publikacyjnego. Brak ruchu agentów.'
              + (' Polityki zysku uczone offline na oddzielnych nagraniach; podczas testu zamrożone.' if learned is not None
                 else ' Brak uczenia polityki.'), '',
              'Pliki: `predictions.csv`, `summary.json`, `models.json`, `config.json` oraz ślady JSONL.']
    (path / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary
