"""Train the gate offline, then compare fixed policies on the official split."""

import numpy as np
from pathlib import Path
from phdsim.artifacts import write_json_atomic as _write
from phdsim.decision.pstnet import LearnedPstPolicy, RgbAcquisitionView
from phdsim.models.linear import LinearModel
from phdsim.evaluation.segmentation import summarize_choices
from phdsim.learning.pstnet.training import fit_acquisition
from .cache import load_cache

def train_and_compare(cache_path, output, *, costs=(0., .001, .005, .01, .02)):
    cached = load_cache(cache_path)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Choose a new output directory for the acquisition experiment')
    rows = cached['rows']
    bundle = fit_acquisition([r for r in rows if r['split'] == 'train'])
    bundle['vision_and_data'] = cached['metadata']
    bundle['predeclared_costs'] = list(costs)
    model = LinearModel.from_dict(bundle['model'])
    test = [r for r in rows if r['split'] == 'test']
    results = {'rgb_only': summarize_choices(test, [False] * len(test)),
               'authors_full_fusion': summarize_choices(test, [True] * len(test))}
    for cost in costs:
        policy = LearnedPstPolicy(model, cost)
        pulls = [policy.acquire(RgbAcquisitionView(tuple(r['features']), r['thermal_bytes'])) for r in test]
        results[f'learned_cost_{cost:g}'] = summarize_choices(test, pulls)
        # Matched-count random controls are diagnostic comparisons, not tuned policies.
        for seed in (17, 42, 97):
            random = np.zeros(len(test), dtype=bool)
            random[np.random.default_rng(seed).permutation(len(test))[:sum(pulls)]] = True
            results[f'random_count_cost_{cost:g}_seed_{seed}'] = summarize_choices(test, random)
    for threshold in (.25, .5, .75):
        results[f'entropy_{threshold:g}'] = summarize_choices(test, [r['features'][0] >= threshold for r in test])
    report = {'schema': 'phdsim-pstnet-comparison-v1', 'test_frames': len(test),
              'published_reference_miou': {'rgb_only': .6765786209506062, 'authors_full_fusion': .6836562966338},
              'reference_differences': {'rgb_only': results['rgb_only']['miou'] - .6765786209506062,
                                        'authors_full_fusion': results['authors_full_fusion']['miou'] - .6836562966338},
              'numerical_reproduction_verified': all(abs(results[k]['miou'] - target) < .001 for k, target in
                                                      [('rgb_only', .6765786209506062), ('authors_full_fusion', .6836562966338)]),
              'timing': 'offline cache comparison; no online latency claim. Use pstnet-run for measured gated replay',
              'selection': 'cost grid declared before test; no winning test setting selected', 'results': results}
    _write(output / 'acquisition.json', bundle)
    _write(output / 'comparison.json', report)
    from .report import write_comparison
    write_comparison(output / 'comparison.md', report)
    return report

