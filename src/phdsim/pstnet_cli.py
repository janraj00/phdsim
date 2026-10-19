"""Compatibility entry point; prefer `python -m phdsim.cli pstnet`."""

from phdsim.cli.pstnet import main, status

if __name__ == '__main__':
    main()
