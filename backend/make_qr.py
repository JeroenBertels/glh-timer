from pathlib import Path
import qrcode

OUT = Path("qr_out")
OUT.mkdir(exist_ok=True)

for bib in range(1, 201):
    img = qrcode.make(str(bib))   # encode just the number
    img.save(OUT / f"bib_{bib}.png")

print("Saved to", OUT.resolve())
