"""从 assets/brand/logo.svg 导出各尺寸图标。

用法：uv run python scripts/build_icons.py
依赖：resvg-py（SVG 渲染，Windows / Linux 都有现成 wheel，无需本地运行库）、Pillow（生成 ICO）。
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import resvg_py
from PIL import Image

BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"


def render(svg: str, size: int) -> Image.Image:
    png = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def main() -> None:
    svg = (BRAND / "logo.svg").read_text(encoding="utf-8")
    shutil.copyfile(BRAND / "logo.svg", BRAND / "favicon.svg")
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png"), (512, "logo.png")]:
        render(svg, size).save(BRAND / name)
    big = render(svg, 256)
    big.save(BRAND / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    big.save(BRAND / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("已导出：", ", ".join(sorted(p.name for p in BRAND.iterdir())))


if __name__ == "__main__":
    main()
