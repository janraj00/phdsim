"""PSTNet reproduction and explicit own RGB training; no implicit weight fallback."""

from argparse import ArgumentParser
import json
from pathlib import Path
import importlib.util


def status(settings):
    manifest = Path(settings['manifest'])
    weights = {name: {'path': settings[name], 'present': Path(settings[name]).is_file()}
               for name in ('rgb_weights', 'fusion_weights')}
    available = all(w['present'] for w in weights.values())
    result = {'schema': 'phdsim-pstnet-status-v1',
              'upstream_commit': '47bbf0133b29e05c7a087b71fb27e8cd8c092ec8',
              'weights': weights, 'dataset_manifest': str(manifest), 'dataset_present': manifest.is_file(),
              'opencv_present': importlib.util.find_spec('cv2') is not None,
              'official_weight_links_checked_2026_10_17': {'dropbox': 'HTML error page, not ZIP', 'google_drive': 'HTTP 404'},
              'architecture_implemented': True, 'learned_acquisition_implemented': True,
              'numerical_reproduction': 'not run; official checkpoints unavailable' if not available else 'requires full benchmark run',
              'ready_for_cache': available and manifest.is_file() and importlib.util.find_spec('cv2') is not None}
    if manifest.is_file():
        value = json.loads(manifest.read_text(encoding='utf-8'))
        result['dataset_pairs'] = value['pairs']
        result['dataset_split'] = value['source_split']
    return result


def main(argv=None):
    parser = ArgumentParser(prog='phdsim pstnet', description=__doc__)
    parser.add_argument('action', choices=('status', 'prepare', 'cache', 'learn', 'run', 'train-rgb'))
    parser.add_argument('--config', type=Path, default=Path('configs/pstnet/experiment.json'))
    parser.add_argument('--cost', type=float, default=.005)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--training-config', type=Path, default=Path('configs/pstnet/rgb_pilot.json'))
    parser.add_argument('--model-directory', type=Path, default=Path('D:/Doktorat/Platforma/models/pstnet_rgb_pilot_v1'))
    args = parser.parse_args(argv)
    settings = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if args.action == 'status':
        result = status(settings)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    elif args.action == 'prepare':
        from phdsim.datasets.pst900.segmentation import prepare_full_dataset
        frames = prepare_full_dataset(settings['data'])
        result = {'prepared_pairs': len(frames), 'manifest': settings['manifest']}
    elif args.action == 'train-rgb':
        from phdsim.perception.pstnet.training.config import RgbTrainingConfig
        from phdsim.perception.pstnet.training.trainer import train_rgb_pilot
        trained = train_rgb_pilot(settings['manifest'], args.output or 'runs/pstnet_rgb_pilot',
                                  args.model_directory, RgbTrainingConfig.load(args.training_config))
        result = {k: trained[k] for k in ('status', 'selected_epoch', 'selected_train', 'selected_validation', 'checkpoint')}
    else:
        from phdsim.experiments.pstnet.cache import collect_cache
        from phdsim.experiments.pstnet.acquisition import train_and_compare
        from phdsim.experiments.pstnet.replay import run_gated
        if args.action == 'cache':
            cache = collect_cache(settings['manifest'], settings['rgb_weights'], settings['fusion_weights'],
                                  args.output or settings['cache'], device=settings['device'], threads=settings['threads'])
            result = {'cached_frames': len(cache['rows'])}
        elif args.action == 'learn':
            report = train_and_compare(settings['cache'], args.output or settings['experiment_output'],
                                       costs=tuple(settings['costs']))
            result = {k: {name: v[name] for name in ('miou', 'pulls', 'transferred_bytes')}
                      for k, v in report['results'].items()}
        else:
            result = run_gated(settings['manifest'], settings['rgb_weights'], settings['fusion_weights'],
                               Path(settings['experiment_output']) / 'acquisition.json',
                               args.output or settings['replay_output'], cost=args.cost,
                               device=settings['device'], threads=settings['threads'])
            result = {k: v for k, v in result.items() if k != 'trace'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
