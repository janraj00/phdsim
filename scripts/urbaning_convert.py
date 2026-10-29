"""Convert a prepared source view with the pinned external UrbanIng SDK (Python 3.10+)."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phdsim.experiments.urbaning_stage1 import prepare_upstream


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--source-view', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    upstream, source, output = (Path(value).resolve() for value in
                                (args.upstream, args.source_view, args.output))
    revision = prepare_upstream(upstream)
    record = json.loads((source / 'phdsim-conversion.json').read_text())
    if sorted(path.name for path in (source / 'dataset').iterdir()) != [record['sequence']]:
        raise ValueError('Source view must contain exactly the declared sequence')
    if output.exists():
        raise FileExistsError('Conversion output must be a new directory')
    sys.path.insert(0, str(upstream / 'urbaning'))
    from urbaning.converters import urbaning_to_opencood_format

    # Upstream converter creates its own output. It may process RGB alongside
    # LiDAR; images are not model inputs for this experiment.
    urbaning_to_opencood_format(str(source), str(output), use_multiprocessing=False)
    record.update(converter_commit=revision, converter='urbaning.converters.opencood')
    (output / 'phdsim-conversion.json').write_text(json.dumps(record, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
