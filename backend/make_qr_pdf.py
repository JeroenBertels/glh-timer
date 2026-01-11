#!/usr/bin/env python3
"""Generate a printable PDF with QR codes + big bib numbers.

Usage examples:
  python make_qr_pdf.py --start 1 --end 200 --out bib_qr.pdf
  python make_qr_pdf.py --start 1 --end 120 --cols 4 --rows 6 --size-mm 45 --out labels.pdf

Notes:
- The QR encodes JUST the bib number (e.g. "37").
- Default layout is an A4 sheet with a reasonable label grid.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from math import floor

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


def make_qr_png_bytes(text: str, box_size: int = 10, border: int = 2) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    bio = BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1, help="First bib number (inclusive)")
    ap.add_argument("--end", type=int, default=200, help="Last bib number (inclusive)")
    ap.add_argument("--out", type=str, default="bib_qr.pdf", help="Output PDF filename")

    ap.add_argument("--pagesize", type=str, default="A4", choices=["A4"], help="Page size")
    ap.add_argument("--margin-mm", type=float, default=10.0, help="Page margin in mm")
    ap.add_argument("--gap-mm", type=float, default=4.0, help="Gap between labels in mm")

    ap.add_argument("--cols", type=int, default=4, help="Number of columns")
    ap.add_argument("--rows", type=int, default=6, help="Number of rows")

    ap.add_argument("--size-mm", type=float, default=45.0, help="Label square size in mm (QR + text area)")
    ap.add_argument("--qr-mm", type=float, default=33.0, help="QR size in mm inside label")
    ap.add_argument("--font", type=str, default="Helvetica-Bold", help="Font name")
    ap.add_argument("--font-size", type=float, default=14.0, help="Bib font size")

    args = ap.parse_args()

    if args.end < args.start:
        raise SystemExit("--end must be >= --start")

    if args.qr_mm > args.size_mm:
        raise SystemExit("--qr-mm must be <= --size-mm")

    page_w, page_h = A4
    margin = args.margin_mm * mm
    gap = args.gap_mm * mm
    label = args.size_mm * mm
    qr_size = args.qr_mm * mm

    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin

    # Simple fit check
    needed_w = args.cols * label + (args.cols - 1) * gap
    needed_h = args.rows * label + (args.rows - 1) * gap
    if needed_w > usable_w + 1e-6 or needed_h > usable_h + 1e-6:
        raise SystemExit(
            f"Grid does not fit on A4 with current settings. "
            f"Needed: {needed_w/mm:.1f}x{needed_h/mm:.1f}mm, "
            f"Usable: {usable_w/mm:.1f}x{usable_h/mm:.1f}mm. "
            f"Try fewer rows/cols, smaller --size-mm, or smaller margins."
        )

    per_page = args.cols * args.rows
    bibs = list(range(args.start, args.end + 1))

    c = canvas.Canvas(args.out, pagesize=A4)
    c.setTitle("GLH bib QR codes")

    def draw_label(x: float, y: float, bib: int):
        # label area: (x,y) is bottom-left
        # center QR horizontally, place near top with some padding
        pad = 2 * mm
        qr_x = x + (label - qr_size) / 2
        qr_y = y + (label - qr_size) - pad - (args.font_size * 0.4)  # leave room for text

        png = make_qr_png_bytes(str(bib))
        img = ImageReader(BytesIO(png))
        c.drawImage(img, qr_x, qr_y, width=qr_size, height=qr_size, preserveAspectRatio=True, mask="auto")

        # Bib text centered at bottom
        c.setFont(args.font, args.font_size)
        text = str(bib)
        c.drawCentredString(x + label / 2, y + pad, text)

        # Optional: light crop marks border (comment out if you don't want it)
        # c.rect(x, y, label, label, stroke=1, fill=0)

    idx = 0
    while idx < len(bibs):
        # draw grid top-to-bottom
        for r in range(args.rows):
            for col in range(args.cols):
                if idx >= len(bibs):
                    break
                bib = bibs[idx]
                x = margin + col * (label + gap)
                # y origin at bottom; place first row at top usable area
                y = (page_h - margin - label) - r * (label + gap)
                draw_label(x, y, bib)
                idx += 1
        if idx < len(bibs):
            c.showPage()

    c.save()
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
