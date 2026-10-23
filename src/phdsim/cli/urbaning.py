"""Explicit source preparation and offline UrbanIng inspection commands."""

from argparse import ArgumentParser
import json
import sys

from phdsim.datasets.urbaning.source import DEFAULT_SEQUENCE


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'cobevt':
        from phdsim.experiments.urbaning_stage1 import main as stage1_main
        return stage1_main(arguments[1:])
    parser = ArgumentParser(prog='phdsim urbaning')
    parser.add_argument('action', choices=('fetch', 'extract', 'inspect', 'opencood-view'),
                        help='Source preparation; also use: urbaning cobevt --help')
    parser.add_argument('--root', default=r'D:\Doktorat\Platforma\data\urbaning-v2x')
    parser.add_argument('--sequence', default=DEFAULT_SEQUENCE)
    parser.add_argument('--output', default='runs/urbaning_inspection')
    parser.add_argument('--frame', type=int, default=100)
    parser.add_argument('--max-frames', type=int, help='Optional conversion-source view limit')
    parser.add_argument('--start-frame', type=int, default=0, help='Conversion-source frame offset')
    args = parser.parse_args(arguments)
    if args.action == 'fetch':
        from phdsim.datasets.urbaning.source import fetch_sequence
        value = fetch_sequence(args.root, args.sequence)
        print(json.dumps({'sequence': value['sequence_id'], 'verified_files': len(value['files'])}))
    elif args.action == 'extract':
        from phdsim.datasets.urbaning.archive import extract_sequence
        print(extract_sequence(args.root, args.sequence))
    elif args.action == 'opencood-view':
        from phdsim.datasets.urbaning.opencood import create_source_view
        print(create_source_view(args.root, args.sequence, args.output, args.max_frames, args.start_frame))
    else:
        from phdsim.datasets.urbaning.inspection import inspect_sequence
        print(inspect_sequence(args.root, args.sequence, args.output, args.frame))


if __name__ == '__main__':
    main()
