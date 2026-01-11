from pathlib import Path
import qrcode

OUT = Path("qr_out")
OUT.mkdir(exist_ok=True)

START_BIB = 1
END_BIB = 200

for bib in range(START_BIB, END_BIB + 1):
    img = qrcode.make(str(bib))
    img.save(OUT / f"bib_{bib}.png")

print("Saved QR PNGs to:", OUT.resolve())
