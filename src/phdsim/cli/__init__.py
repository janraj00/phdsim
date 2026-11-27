"""Entry point for SCOUT semantic mapping experiments."""

from argparse import ArgumentParser, REMAINDER
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = ArgumentParser(prog='phdsim', description='SCOUT multi-agent semantic terrain mapping benchmark.')
    parser.add_argument('workflow', choices=('scout-bench',),
                        help='Select a SCOUT workflow')
    parser.add_argument('arguments', nargs=REMAINDER, help='Workflow arguments; use <workflow> --help')
    parsed = parser.parse_args(arguments)
    from .scout_bench import main as workflow_main
    return workflow_main(parsed.arguments)
