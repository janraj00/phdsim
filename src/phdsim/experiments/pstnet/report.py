"""Keep published reference scores distinct from measured results."""

from pathlib import Path


def write_comparison(path, report):
    lines = ['# PST900: authors model + learned thermal acquisition', '',
             'Evaluation: all 288 original test frames; sum pixel confusion matrices, then calculate five-class mIoU.',
             'Published values are references, not measurements from this run.', '',
             '| Method | mIoU | Survivor IoU | Pulls | MB |', '|---|---:|---:|---:|---:|']
    for name, result in report['results'].items():
        lines.append(f"| {name} | {result['miou']:.6f} | {result['class_iou']['survivor']:.6f} | {result['pulls']} | {result['transferred_bytes']/1e6:.2f} |")
    lines += ['', f"Numerical reproduction within 0.001 mIoU: {report['numerical_reproduction_verified']}.",
              'Gate target: per-frame IoU improvement; this surrogate does not equal the change in global mIoU.',
              'Only gate parameters are fitted here. Authors pretrained vision experts have seen original train images.',
              'No latency claim from counterfactual cache. Actual gated execution has a separate timing report.',
              'Bytes count the thermal PNG delivered in the simulation; network transport is not simulated.']
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
