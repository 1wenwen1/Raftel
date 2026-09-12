"""Validated adapters; source CSV values are never inferred or repaired."""
import csv
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALIASES = {'Chained': 'Chained-Raftel', 'Hotstuff': 'HotStuff', 'Basic-Damysus': 'Damysus',
           **{f'set{i}': f'S{i}' for i in range(1, 5)}}


def number(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'Invalid nonnegative measurement: {value}')
    return value


def read_curves(path, fig):
    """Return ordered {paper label: [(x, throughput, latency)]}, original flag.

    Original Fig4 contains one duplicate S2 label. Its plotting script places
    all six sorted rows on the common six-position fault axis, so this adapter
    reproduces that explicit positional mapping without changing the raw CSV.
    Fig6 source thread_count is NOT a recoverable offered-load identifier.
    """
    lines = [l for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith('#')]
    if not lines:
        raise ValueError(f'No measurements: {path}')
    original = lines[0].startswith(('TEE nodes,', 'tee_nodes,', 'network,'))
    curves = {}
    if original:
        rows = list(csv.DictReader(lines))
        if fig == 'fig3':
            paired = {}
            for r in rows:
                if r['network'] != 'WAN':
                    continue
                name, x = r['algorithm'], int(r['TEE nodes'])
                paired.setdefault(name, {}).setdefault(x, {})[r['metric']] = number(r['value'])
            for name, points in paired.items():
                curves[name] = [(x, p['throughput'], p['latency']) for x,p in sorted(points.items())]
        elif fig == 'fig4':
            for r in rows:
                curves.setdefault(r['set'], []).append((int(r['tee_nodes']), number(r['throughput']), number(r['latency'])))
            fault_axis = [1, 2, 4, 8, 16, 32]
            for name, points in curves.items():
                points.sort(key=lambda point: point[0])
                if len(points) != len(fault_axis):
                    raise ValueError(
                        f'Original Figure 4 series {name} has {len(points)} rows; '
                        f'expected {len(fault_axis)} for its positional axis'
                    )
                curves[name] = [
                    (fault, point[1], point[2])
                    for fault, point in zip(fault_axis, points)
                ]
        else:
            for r in rows:
                if r['network'] == 'lan' and r['protocol']:
                    curves.setdefault(r['protocol'], []).append((number(r['thread_count']), number(r['avg_qps']), number(r['avg_latency'])))
    elif fig in ('fig3', 'fig4'):
        for index, row in enumerate(csv.reader(lines), 1):
            if len(row) != 3:
                raise ValueError(f'{path}:{index}: expected label, throughput, latency')
            match = re.fullmatch(r'(.+)_f(\d+)', row[0].strip())
            if not match:
                raise ValueError(f'{path}:{index}: invalid configuration label')
            name = ALIASES.get(match[1], match[1]); x = int(match[2])
            points = curves.setdefault(name, [])
            if any(p[0] == x for p in points):
                raise ValueError(f'{path}:{index}: duplicate configuration {name}/f={x}')
            points.append((x, number(row[1]), number(row[2])))
    else:
        for r in csv.DictReader(lines):
            name = ALIASES.get(r['protocol'], r['protocol'])
            x = int(r['load_clients'])
            points = curves.setdefault(name, [])
            if any(p[0] == x for p in points):
                raise ValueError(f'Duplicate load point: {name}/{x}')
            points.append((x, number(r['e2e_throughput_ktps'])*1000, number(r['e2e_latency_avg_ms'])))
    if not curves:
        raise ValueError(f'No usable measurements: {path}')
    for points in curves.values():
        points.sort(key=lambda p:p[0])
    # AE FIX (paper figures): bind appearance to protocol identity, not run order.
    source = REPO/'runs/reference/original/alg_tee_nodes_WAN.csv'
    if fig == 'fig3':
        with source.open(encoding="utf-8") as stream:
            order = list(dict.fromkeys(
                r['algorithm'] for r in csv.DictReader(stream) if r['network'] == 'WAN'
            ))
    else:
        order = sorted(curves)
    unknown = set(curves)-set(order)
    if unknown:
        raise ValueError(f'Unrecognized series: {sorted(unknown)}')
    return {n:curves[n] for n in order if n in curves}, original
