"""Explicit source preparation and offline UrbanIng inspection commands."""

from argparse import ArgumentParser
import json

from phdsim.datasets.urbaning.source import DEFAULT_SEQUENCE


def main(argv=None):
    parser = ArgumentParser(prog='phdsim urbaning')
    parser.add_argument('action', choices=('fetch', 'extract', 'inspect'))
    parser.add_argument('--root', default=r'D:\Doktorat\Platforma\data\urbaning-v2x')
    parser.add_argument('--sequence', default=DEFAULT_SEQUENCE)
    parser.add_argument('--output', default='runs/urbaning_inspection')
    parser.add_argument('--frame', type=int, default=100)
    args = parser.parse_args(argv)
    if args.action == 'fetch':
        from phdsim.datasets.urbaning.source import fetch_sequence
        value = fetch_sequence(args.root, args.sequence)
        print(json.dumps({'sequence': value['sequence_id'], 'verified_files': len(value['files'])}))
    elif args.action == 'extract':
        from phdsim.datasets.urbaning.archive import extract_sequence
        print(extract_sequence(args.root, args.sequence))
    else:
        from phdsim.datasets.urbaning.inspection import inspect_sequence
        print(inspect_sequence(args.root, args.sequence, args.output, args.frame))


if __name__ == '__main__':
    main()
