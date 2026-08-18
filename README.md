# Voya Backend

Small HTTP API that bridges the Voya Customer app and Admin dashboard to a
Google Sheet ("Voya Bookings Live").

## Endpoints

- `GET /api/bookings` — list all bookings (newest first)
- `POST /api/bookings` — create a new booking
- `GET /healthz` — health check

## Environment variables (set in Render dashboard, never committed)

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_SHEET_ID`

## Local development

```bash
pip install -r requirements.txt
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export GOOGLE_REFRESH_TOKEN=...
export GOOGLE_SHEET_ID=...
python app.py
```
