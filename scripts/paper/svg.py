from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

COLORS = {
    "baseline": "#A8B2BF",
    "self_route": "#3978B8",
    "annotated_preload": "#E4764F",
    "grid": "#D9DEE5",
    "text": "#17212B",
    "muted": "#5E6A75",
}


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def document(width: int, height: int, body: Iterable[str]) -> str:
    return "\n".join(
        [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">'
            ),
            "<style>",
            (f"text{{font-family:Helvetica,Arial,sans-serif;fill:{COLORS['text']}}}"),
            ".title{font-size:22px;font-weight:700}",
            ".subtitle{font-size:13px;fill:#5E6A75}",
            ".axis{font-size:12px;fill:#5E6A75}",
            ".label{font-size:12px}",
            ".small{font-size:10px}",
            "</style>",
            '<rect width="100%" height="100%" fill="white"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def write(path: Path, width: int, height: int, body: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document(width, height, body), encoding="utf-8")


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = "#17212B",
    width: float = 1,
    dash: str | None = None,
) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" '
        f'y2="{y2:.2f}" stroke="{stroke}" stroke-width="{width}"'
        f"{dash_attr}/>"
    )


def text(
    x: float,
    y: float,
    value: object,
    *,
    css: str = "label",
    anchor: str = "start",
    rotate: float | None = None,
    fill: str | None = None,
) -> str:
    transform = f' transform="rotate({rotate:.1f} {x:.2f} {y:.2f})"' if rotate is not None else ""
    fill_attr = f' fill="{fill}"' if fill else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" class="{css}" '
        f'text-anchor="{anchor}"{transform}{fill_attr}>'
        f"{escape(value)}</text>"
    )


def rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    stroke: str | None = None,
    radius: float = 0,
) -> str:
    stroke_attr = f' stroke="{stroke}"' if stroke else ""
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" '
        f'height="{height:.2f}" rx="{radius:.2f}" fill="{fill}"'
        f"{stroke_attr}/>"
    )


def circle(
    x: float,
    y: float,
    radius: float,
    *,
    fill: str,
    stroke: str = "#17212B",
) -> str:
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
    )


def interpolate_color(value: float, limit: float = 40.0) -> str:
    normalized = max(-1.0, min(1.0, value / limit))
    if normalized < 0:
        start = (48, 105, 152)
        end = (247, 247, 247)
        weight = normalized + 1.0
    else:
        start = (247, 247, 247)
        end = (178, 40, 53)
        weight = normalized
    channels = [round(start[index] + (end[index] - start[index]) * weight) for index in range(3)]
    return "#" + "".join(f"{channel:02X}" for channel in channels)
