"""Small offline SVG report. Truth is accessed only here and in simulation."""

from html import escape


def render_svg(results: list[dict]) -> str:
    scale = 12
    first = results[0]["evaluation"]
    w, h = len(first["truth"][0]), len(first["truth"])
    panel_w, panel_h = w*scale, h*scale
    columns = 3
    width, height = columns*(panel_w+32)+16, len(results)*(panel_h+128)+64
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#f5f7fa"/>',
           '<style>text {font-family:Arial,sans-serif;fill:#16213a} .title{font-size:17px;font-weight:bold}.small{font-size:12px}</style>',
           '<text x="20" y="26" class="title">SCOUT v0 — synthetic diagnostic, no learned policy</text>',
           '<text x="20" y="47" class="small">Dark = blocked / high P(blocked); blue = rover route; orange = drone targets. Truth is offline only.</text>']
    for row, result in enumerate(results):
        e, s = result["evaluation"], result["summary"]
        top = 90+row*(panel_h+128)
        svg.append(f'<text x="20" y="{top-12}" class="title">{escape(s["policy"])} — {escape(s["status"])}</text>')
        for col, (label, key) in enumerate((("World (offline evaluator)", "truth"),
                                          ("Initial rover prior", "initial_belief"),
                                          ("Final rover belief", "final_belief"))):
            left = 20+col*(panel_w+32)
            svg.append(f'<text x="{left}" y="{top+5}" class="small">{label}</text>')
            y0 = top+16
            for y, cells in enumerate(e[key]):
                for x, p in enumerate(cells):
                    value = int(247-205*float(p))
                    color = f'rgb({value},{value},{min(255,value+8)})'
                    svg.append(f'<rect x="{left+x*scale}" y="{y0+y*scale}" width="{scale}" height="{scale}" fill="{color}" stroke="#d6dbe1" stroke-width="0.25"/>')
            if key != "initial_belief":
                points = ' '.join(f'{left+(v["position"][0]+.5)*scale},{y0+(v["position"][1]+.5)*scale}' for v in result["trajectory"])
                svg.append(f'<polyline points="{points}" fill="none" stroke="#2878d0" stroke-width="3"/>')
                for event in result["events"]:
                    if event["kind"] == "request_accepted":
                        x, y = event["target"]
                        svg.append(f'<circle cx="{left+(x+.5)*scale}" cy="{y0+(y+.5)*scale}" r="5" fill="none" stroke="#e07813" stroke-width="2"/>')
            for label_text, cell, color in (("S", e["start"], "#216b35"), ("G", e["goal"], "#a72d48")):
                x, y = cell
                svg.append(f'<text x="{left+x*scale+2}" y="{y0+(y+1)*scale-1}" font-size="12" font-weight="bold" style="fill:{color}">{label_text}</text>')
        metrics = (f'ticks={s["elapsed_ticks"]} | energy reserved={s["energy_reserved"]:.2f} | '
                   f'requests/delivered={s["requests"]}/{s["delivered"]} | '
                   f'bytes={s["delivered_bytes"]} | blocked attempts={s["blocked_attempts"]}')
        svg.append(f'<text x="20" y="{top+panel_h+42}" class="small">{escape(metrics)}</text>')
    svg.append('</svg>')
    return '\n'.join(svg)
