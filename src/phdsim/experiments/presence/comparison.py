"""Compare acquisition objectives on paired predictions without selecting on test."""

import csv
import json
from math import isclose
from pathlib import Path

from phdsim.datasets import write_json


def _prediction_changes(root, method, modality=None):
    with (root / method / 'results/predictions.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    changes = {}
    for row in rows:
        if modality is not None and row['own_modality'] != modality:
            continue
        item = changes.setdefault(row['policy'], {'repairs': 0, 'damages': 0, 'unchanged_pulls': 0})
        before = (float(row['probability_before']) >= 0.5) == bool(int(row['reference_label']))
        after = (float(row['probability_after']) >= 0.5) == bool(int(row['reference_label']))
        item['repairs'] += int(not before and after)
        item['damages'] += int(before and not after)
        item['unchanged_pulls'] += int(row['transfers']) - int(before != after)
    return changes


def write_objective_comparison(reference, current):
    reference, current = Path(reference), Path(current)
    previous = json.loads((reference / 'comparison.json').read_text(encoding='utf-8'))
    present = json.loads((current / 'comparison.json').read_text(encoding='utf-8'))
    old = {(r['fusion'], r['policy']): r for r in previous['rows']}
    methods = ('mean_probability', 'learned_probability')
    changes = {(str(root), method): _prediction_changes(root, method)
               for root in (reference, current) for method in methods}
    for row in present['rows']:
        if not row['method'].startswith('learned_gain'):
            baseline = old[row['fusion'], row['policy']]
            if any(not isclose(row[k], baseline[k], rel_tol=0, abs_tol=1e-12)
                   for k in ('accuracy', 'brier', 'transfers', 'bytes')):
                raise ValueError('Control results changed despite fixed perception, fusion and policies')
    selected = []
    for row in present['rows']:
        if row['method'].startswith('learned_gain') and row['transfer_penalty'] == 0:
            for source, data, metric in ((reference, old[row['fusion'], row['policy']], previous['config'].get('gain_metric', 'brier')),
                                         (current, row, present['config']['gain_metric'])):
                counts = changes[str(source), row['fusion']][row['policy']]
                selected.append({**data, 'gain_metric': metric, **counts})
    write_json(current / 'objective_comparison.json', {'reference': str(reference), 'current': str(current),
               'control_results': 'identical', 'rows': selected,
               'scope': 'fixed CNNs, fusions, data roles and parameter grids; zero transfer penalty, not selected by test score'})
    lines = ['# Zmiana celu akwizycji: Brier → poprawność rozpoznawania', '',
             'Te same CNN, dokładnie te same wagi fuzji, podział 121/48/70/160 i siatka parametrów. '
             'Wyniki wszystkich strategii kontrolnych pozostały identyczne. Zmieniony jest cel uczenia modeli akwizycji.', '',
             'Nowy cel: +1 za naprawienie błędu, -1 za zepsucie poprawnej odpowiedzi, 0 w pozostałych przypadkach. '
             'Próg klasyfikacji pozostaje 0,5. Model przewiduje średni zysk z własnych informacji, przed transferem.', '',
             'Poniżej wszystkie warianty uczone przy zerowej karze transferu; nie wybieramy kosztu na podstawie testu. '
             'Trafność jest średnią dla obu agentów. Naprawy i pogorszenia dotyczą odpowiedzi agent–klatka.', '',
             '| Fuzja | Cechy akwizycji | Cel uczenia | Trafność | Naprawy | Pogorszenia | Pobrania |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    for row in selected:
        variant = 'wynik + cechy obrazu' if row['method'] == 'learned_gain' else 'wynik i niepewność'
        lines.append(f'| {row["fusion"]} | {variant} | {row["gain_metric"]} | {row["accuracy"]:.2%} | '
                     f'{row["repairs"]} | {row["damages"]} | {row["transfers"]} |')
    own = next(r for r in present['rows'] if r['fusion'] == 'mean_probability' and r['method'] == 'no_acquisition')
    mean = next(r for r in present['rows'] if r['fusion'] == 'mean_probability' and r['method'] == 'always_acquire')
    learned = next(r for r in present['rows'] if r['fusion'] == 'learned_probability' and r['method'] == 'always_acquire')
    lines += ['', f'Kontrole: własna obserwacja {own["accuracy"]:.2%}; zawsze + średnia {mean["accuracy"]:.2%}; '
              f'zawsze + uczona fuzja {learned["accuracy"]:.2%}.', '',
              '## Pełna ustalona siatka kosztów: nowy cel i cechy obrazu', '',
              '| Fuzja | Kara za pobranie | Trafność | Naprawy | Pogorszenia | Pobrania | MB |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in present['rows']:
        if row['method'] != 'learned_gain':
            continue
        counts = changes[str(current), row['fusion']][row['policy']]
        lines.append(f'| {row["fusion"]} | {row["transfer_penalty"]:g} | {row["accuracy"]:.2%} | '
                     f'{counts["repairs"]} | {counts["damages"]} | {row["transfers"]} | {row["bytes"] / 1_000_000:.2f} |')
    meta = []
    with (current / 'mean_probability/models/meta_samples.jsonl').open(encoding='utf-8') as stream:
        meta = [json.loads(line) for line in stream if line.strip()]
    if present['config']['gain_metric'] == 'classification_error':
        lines += ['', '## Reprezentatywność przykładów dla fuzji średniej', '',
                  '| Własna modalność | Naprawy w meta | Pogorszenia w meta | Naprawy na teście | Pogorszenia na teście |',
                  '| --- | ---: | ---: | ---: | ---: |']
        for modality in ('rgb', 'thermal'):
            test = _prediction_changes(current, 'mean_probability', modality)['always_acquire']
            positive = sum(s[f'{modality}_gain'] > 0 for s in meta)
            negative = sum(s[f'{modality}_gain'] < 0 for s in meta)
            lines.append(f'| {modality} | {positive} | {negative} | {test["repairs"]} | {test["damages"]} |')
        lines += ['', 'W przykładach meta dla RGB nie występuje szkodliwe pobranie, choć na teście takie przypadki są obecne. '
                  'To wskazuje na problem z przeniesieniem reguły między nagraniami. '
                  'Etykiety testowe służą tutaj wyłącznie diagnozie; nie poprawiamy według nich modelu.']
    lines += ['',
              'Test był już wcześniej oglądany i wpłynął na pomysł zmiany celu; to eksperyment diagnostyczny. '
              'Etykiety testowe nie służą do uczenia wag ani wyboru regularyzacji. '
              'Pełna siatka kosztów i losowe kontrole są w report.md i comparison.csv.']
    (current / 'objective_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
