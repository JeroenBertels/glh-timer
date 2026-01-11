# GLH Timer (local-first swim-run timing)

This project is a small, local-first web app to manage **races**, **race parts** (swim/run),
**participants**, and **timing events**, with live-updating results and an organizer (admin) mode.

It’s designed to run **locally on your Mac** first (SQLite database), and later you can host it.

---

## 1) Quick start (Mac / Linux)

### Prereqs
- Python 3.11+ recommended (3.10 works too)
- Terminal

### Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure admin password
Create a file `.env` inside `backend/`:

```bash
# backend/.env
GLH_ADMIN_USERNAME=admin
GLH_ADMIN_PASSWORD=change-me
GLH_SECRET_KEY=dev-secret-change-me
GLH_DB_URL=sqlite:///./glh_timer.db
```

### Run
```bash
uvicorn app.main:app --reload
```

Open:
- http://127.0.0.1:8000

---

## 2) What you can do

### Public (no login)
- Landing page → Projects → GLH Timer
- View races
- View race parts
- View live results (auto-refresh every 5 seconds)

### Organizer (admin login)
- Add race
- Add race part (swim/run, by duration or by end-time)
- Add participants
- Set start times per group (for end-time parts)
- Submit timing events:
  - **By duration**: bib + duration (HH:MM:SS or MM:SS or seconds)
  - **By end-time**: bib + submit (server time stored automatically, with optional client-side backup)
- Download CSV exports

### Overall results
Each race has an **Overall** part automatically (created at race creation time).
Overall is computed as the sum of each participant’s best durations for all non-overall parts.

---

## 3) Notes & tips

### “By end time” parts need a start time
To compute durations for end-time parts you must set a start time for each participant group
(or a “DEFAULT” group start time). You can do this from the race part page (admin button).

### QR scanning for run finish
On the “Submit timing event” page for an end-time part, there’s a QR scanner that:
- uses your phone camera in the browser
- fills in the bib number
- auto-submits

It uses a small CDN JS library (`html5-qrcode`). For a fully offline setup later you can vendor the library.

---

## 4) CSV exports

- `/api/races.csv`
- `/api/race-parts.csv?race_id=...` (optional filter)
- `/api/participants.csv?race_id=...` (optional filter)
- `/api/timing-events.csv?race_id=...` (optional filter)

---

## 5) Hosting later + custom domain (bertels.ai)

When you’re ready to host, a typical path is:
- Run this app on a small VM (e.g. Hetzner / DigitalOcean) or a platform (Render/Fly.io)
- Put Nginx (or the platform’s router) in front
- Point `glh-timer.bertels.ai` or `bertels.ai/glh-timer` to it
- Set secure `GLH_SECRET_KEY` and stronger admin password

If you tell me where your domain is managed (Squarespace, Cloudflare, etc.) and where you want to host,
I can give a concrete step-by-step deployment + DNS plan.

---

## 6) Project layout

```
backend/
  app/
    main.py
    settings.py
    db.py
    models.py
    schemas.py
    services.py
    auth.py
    csv_export.py
    templates/
    static/
```

---

## License
MIT (feel free to modify for your club)


## QR code printing (PDF)

Generate a printable A4 PDF with QR codes + big bib numbers:

```bash
cd backend
source .venv/bin/activate
python make_qr_pdf.py --start 1 --end 200 --out bib_qr.pdf
```

Then print `bib_qr.pdf` and cut/tape labels to bibs.
You can tweak the grid/layout, e.g.:

```bash
python make_qr_pdf.py --start 1 --end 120 --cols 4 --rows 6 --size-mm 45 --qr-mm 33 --out labels.pdf
```
