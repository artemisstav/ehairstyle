# ✂️ ehairstyle — Online Booking (MVP)

**Σημείωση:** Αυτό είναι *πρωτότυπο* demo (τύπου online booking), χωρίς να αντιγράφει branding/γραφικά/κώδικα τρίτων.

## Features
- Λίστα καταστημάτων (αναζήτηση/φίλτρα)
- Σελίδα καταστήματος: υπηρεσίες, προσωπικό, αξιολογήσεις
- Ραντεβού: Ημερομηνία → Υπηρεσία → Υπάλληλος → Ώρα → Επιβεβαίωση
- Διαθέσιμα slots με βάση ωράριο + υπάρχοντα ραντεβού
- Admin panel: καταστήματα/υπηρεσίες/υπάλληλοι/ωράριο/ραντεβού

## Default Admin
- /admin
- Password: admin  (άλλαξέ το με env var `ADMIN_PASSWORD`)

## Local run (Windows / VS Code)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```
Open: http://127.0.0.1:5000

## Public deploy (Render)
Env vars: SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL (Postgres)

Start:
```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```


## Αν σου βγάλει error σε Windows για psycopg2 / pg_config
Το app τρέχει τοπικά με SQLite και ΔΕΝ χρειάζεται Postgres driver.
Χρησιμοποίησε μόνο το `requirements.txt`.

Για Postgres (σε hosting), τότε εγκαθιστάς επιπλέον:
```powershell
python -m pip install -r requirements-postgres.txt
```
