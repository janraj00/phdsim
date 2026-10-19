"""Record selected real Python calls without adding logging to model/runtime code."""

import inspect
from pathlib import Path
import sys


def describe(value):
    """Summarize returned data without embedding images, tensors or model weights."""
    if hasattr(value, 'shape'):
        return {'type': type(value).__name__, 'shape': list(value.shape)}
    if hasattr(value, 'prediction'):
        return {'prediction': value.prediction, 'uncertainty': value.uncertainty,
                'observations': list(value.observation_ids)}
    if hasattr(value, 'acquired'):
        return {'acquired': value.acquired, 'transferred_bytes': value.transferred_bytes,
                'mask_shape': list(value.final_mask.shape)}
    if hasattr(value, 'receiver_id'):
        return {'choice': type(value).__name__, 'receiver': value.receiver_id,
                'reason': getattr(value, 'reason', None)}
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (tuple, list, dict)):
        return {'type': type(value).__name__, 'items': len(value)}
    return {'type': type(value).__name__}


class CallTrace:
    """Trace only registered functions; restore the caller's profiler on exit."""

    def __init__(self):
        self.rows = []
        self._watched = {}
        self._stack = []

    def watch(self, function, explanation):
        function = inspect.unwrap(getattr(function, '__func__', function))
        code = function.__code__
        self._watched[code] = {
            'name': function.__qualname__, 'explanation': explanation,
            'source': Path(code.co_filename).resolve().as_posix(),
            'line': code.co_firstlineno,
        }

    def event(self, name, details):
        self.rows.append({'kind': 'event', 'name': name, 'depth': len(self._stack),
                          'details': details})

    def _profile(self, frame, event, value):
        if event not in ('call', 'return') or frame.f_code not in self._watched:
            return
        if event == 'call':
            row = {'kind': 'call', **self._watched[frame.f_code], 'depth': len(self._stack)}
            self.rows.append(row)
            self._stack.append(row)
        elif self._stack:
            self._stack.pop()['returned'] = describe(value)

    def __enter__(self):
        self._previous = sys.getprofile()
        sys.setprofile(self._profile)
        return self

    def __exit__(self, *error):
        sys.setprofile(self._previous)


def render_trace(title, intro, rows, summary):
    """Use current source positions; generated reports point to actual local files."""
    import json
    lines = [f'## {title}', '', intro, '', 'Wynik przebiegu:', '', '```json',
             json.dumps(summary, ensure_ascii=False, indent=2), '```', '',
             '| Krok | Wywołanie / zdarzenie | Co się dzieje / co wraca |',
             '| ---: | --- | --- |']
    for number, row in enumerate(rows, 1):
        if row['kind'] == 'call':
            label = '[' + row['name'] + '](' + row['source'] + ':' + str(row['line']) + ')'
            detail = row['explanation'] + ' → `' + json.dumps(row.get('returned'), ensure_ascii=False) + '`'
        else:
            label = '**' + row['name'] + '**'
            detail = '`' + json.dumps(row['details'], ensure_ascii=False) + '`'
        lines.append(f'| {number} | {"↳ " * row["depth"]}{label} | {detail.replace("|", "&#124;")} |')
    return '\n'.join(lines) + '\n'
