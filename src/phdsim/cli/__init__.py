"""One entry point with explicit task workflows and source data inspection."""

from argparse import ArgumentParser, REMAINDER
import sys

PRESENCE_COMMANDS = frozenset(('inspect', 'fetch', 'prepare-pst900', 'review-pst900',
                               'train-cnn', 'learn-acquisition', 'prepare', 'allocate', 'run'))


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Keep earlier `phdsim <presence-command>` calls working without duplicating implementations.
    if arguments and arguments[0] in PRESENCE_COMMANDS:
        from .presence import main as presence_main
        return presence_main(arguments)
    parser = ArgumentParser(prog='phdsim', description='Selective acquisition of existing peer observations.')
    parser.add_argument('workflow', choices=('pstnet', 'presence', 'urbaning'),
                        help='pstnet: segmentation; presence: classification; urbaning: source preparation and CoBEVT')
    parser.add_argument('arguments', nargs=REMAINDER, help='Workflow arguments; use <workflow> --help')
    parsed = parser.parse_args(arguments)
    if parsed.workflow == 'pstnet':
        from .pstnet import main as workflow_main
    elif parsed.workflow == 'urbaning':
        from .urbaning import main as workflow_main
    else:
        from .presence import main as workflow_main
    return workflow_main(parsed.arguments)
