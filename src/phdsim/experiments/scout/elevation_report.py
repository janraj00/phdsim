"""Plot mean offline coverage over elapsed time with one curve per strategy."""

from statistics import mean


def coverage_svg(groups: dict[str, list[dict]], time_budget: int, target: float) -> str:
    x0, y0, width, height = 70, 52, 610, 280

    def x(tick):
        return x0 + width * tick / time_budget

    def y(fraction):
        return y0 + height * (1 - fraction)

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="720" height="418" '
             'viewBox="0 0 720 418" role="img" aria-label="Elevation accuracy over time">',
             '<rect width="720" height="418" fill="#ffffff"/>',
             '<g font-family="sans-serif" fill="#182632" font-size="13">',
             '<text x="70" y="27" font-size="19">Surface within the elevation error tolerance</text>']
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<line x1="{x0}" x2="{x0 + width}" y1="{y(fraction)}" '
                     f'y2="{y(fraction)}" stroke="#dde4ec"/>')
        parts.append(f'<text x="57" y="{y(fraction) + 4}" text-anchor="end">{fraction:.0%}</text>')
    for tick in sorted({round(time_budget * step / 6) for step in range(7)}):
        parts.append(f'<text x="{x(tick)}" y="353" text-anchor="middle">{tick}</text>')
    parts.extend([f'<line x1="{x0}" x2="{x0 + width}" y1="{y(target)}" '
                  f'y2="{y(target)}" stroke="#687886" stroke-dasharray="6 5"/>',
                  '<text x="375" y="375" text-anchor="middle">Elapsed time (simulated ticks)</text>'])
    for index, (policy, color, label) in enumerate((
            ("fixed", "#ad4d24", "Fixed plan"), ("adaptive", "#006987", "Adaptive plan"))):
        runs = [result["trace"] for result in groups[policy]]
        points = []
        positions = [0] * len(runs)
        for tick in range(time_budget + 1):
            for i, trace in enumerate(runs):
                while positions[i] + 1 < len(trace) and trace[positions[i] + 1]["tick"] <= tick:
                    positions[i] += 1
            average = mean(trace[pos]["actual_fraction"] for pos, trace in zip(positions, runs, strict=True))
            if points:
                points.append((x(tick), points[-1][1]))
            points.append((x(tick), y(average)))
        coordinates = ' '.join(f'{px:.2f},{py:.2f}' for px, py in points)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{coordinates}"/>')
        parts.append(f'<text x="{80 + index * 150}" y="402" fill="{color}">{label}</text>')
    parts.append(f'<text x="380" y="402">Dashed line: {target:.0%} coverage target</text></g></svg>')
    return '\n'.join(parts)
