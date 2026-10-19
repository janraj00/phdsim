"""Collect and validate paired offline samples from the reserved meta recordings."""

from phdsim.datasets.pst900.review import recording_family
from phdsim.perception import load_observation


def collect_meta_samples(pool, trained, plan):
    scope = set(plan['sequences']['meta_train'])
    fitted = trained.model_snapshot.get('training_sequences')
    if fitted is None or set(fitted) != set(plan['sequences']['cnn_train']) or scope & set(fitted):
        raise ValueError('Use fresh CNNs fitted without the meta recordings')
    selected = [r for r in pool.records if r.sequence_id in scope]
    if not selected or any(r.split != 'train' for r in selected):
        raise ValueError('Meta fitting must use train recordings only')
    labels, paired = pool.read_labels(), {}
    for row in selected:
        result = trained.perception.process(load_observation(pool, row))
        if len(result.evidence) != 1 or result.evidence[0].modality != row.modality:
            raise ValueError('Perception must expose evidence for the delivered modality')
        sample = paired.setdefault(row.target, {'target': row.target, 'group': recording_family(row.sequence_id),
                                               'label': labels[row.target]})
        if row.modality in sample:
            raise ValueError('Duplicate meta modality')
        sample[row.modality] = result.evidence[0]
    samples = [paired[target] for target in sorted(paired, key=lambda t: (t.kind, t.id))]
    if any(set(s) != {'target', 'group', 'label', 'rgb', 'thermal'} for s in samples):
        raise ValueError('Meta fitting requires complete RGB/thermal pairs')
    if {s['label'] for s in samples} != {0, 1} or len({s['group'] for s in samples}) < 3:
        raise ValueError('Meta data needs both labels and at least three recording families')
    return samples


def validate_meta_samples(pool, plan, samples):
    """Check sample membership and references before any meta model is fitted."""
    meta_rows = [r for r in pool.records if r.sequence_id in plan['sequences']['meta_train']]
    expected = {r.target for r in meta_rows}
    labels = pool.read_labels()
    if (plan['pool_fingerprint'] != pool.fingerprint or len({s['group'] for s in samples}) < 3
            or {s['target'] for s in samples} != expected or len(samples) != len(expected)):
        raise ValueError('Samples must belong to the meta plan')
    by_target_modality = {(r.target, r.modality): r for r in meta_rows}
    for sample in samples:
        if sample['label'] != labels[sample['target']]:
            raise ValueError('Meta sample label differs from reference')
        for modality in ('rgb', 'thermal'):
            record = by_target_modality[sample['target'], modality]
            if (record.split != 'train' or sample['group'] != recording_family(record.sequence_id)
                    or sample[modality].observation_id != record.observation_id or sample[modality].modality != modality):
                raise ValueError('Meta sample evidence or recording family differs')
