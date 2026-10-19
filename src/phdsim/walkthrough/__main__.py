"""Generate an executed call-by-call reading guide with current source links."""

from argparse import ArgumentParser
from datetime import datetime
import json
from pathlib import Path

from .trace import render_trace


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--workflow', choices=('all', 'pstnet', 'presence'), default='all')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pool', type=Path, default=Path('D:/Doktorat/Platforma/data/pst900/pool_cnn_v1'))
    parser.add_argument('--models', type=Path, default=Path('D:/Doktorat/Platforma/models/pst900_resnet18_v1'))
    parser.add_argument('--schedule', type=Path, default=Path('runs/pst900_cnn/schedule.json'))
    args = parser.parse_args(argv)
    output = (args.output or Path('runs/walkthrough') / datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    if output.exists():
        raise FileExistsError('Walkthrough output exists; select a new directory')
    if args.workflow in ('all', 'presence'):
        for path in (args.pool / 'pool.json', args.models / 'models.json', args.schedule):
            if not path.is_file():
                raise FileNotFoundError(f'Presence walkthrough requires existing data/models: {path}')
    import torch
    torch.set_num_threads(2)
    output.mkdir(parents=True)
    scenarios = []
    if args.workflow in ('all', 'pstnet'):
        from .pstnet import run_pstnet
        scenarios.extend(run_pstnet(output / 'pstnet_inputs'))
    if args.workflow in ('all', 'presence'):
        from .presence import run_presence
        scenarios.extend(run_presence(args.pool, args.schedule, args.models))
    (output / 'steps.json').write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding='utf-8')
    text = ['# Symulacja: wykonane wywołania i kod', '',
            'Linki wskazują pliki i numery linii z chwili wykonania. Wiersze są rzeczywistymi wywołaniami, '
            'przechwyconymi przez profiler Pythona. Tabela pokazuje moment wejścia do funkcji; ostatnia kolumna '
            'uzupełnia go o podsumowanie wartości zwróconej. Zagnieżdżenie oznacza wywołanie wewnętrzne.', '',
            'PSTNet pokazuje obie gałęzie na syntetycznych wejściach i losowych wagach. Presence używa '
            'jednej rzeczywistej klatki oraz istniejących wytrenowanych klasyfikatorów.', '']
    text.extend(render_trace(s['title'], s['intro'], s['steps'], s['summary']) for s in scenarios)
    report = output / 'walkthrough.md'
    report.write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({'report': str(report), 'scenarios': len(scenarios),
                      'steps': sum(len(s['steps']) for s in scenarios)}, indent=2))
    return scenarios


if __name__ == '__main__':
    main()
