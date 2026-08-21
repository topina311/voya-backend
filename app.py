"""
Voya booking backend — bridges the Customer app + Admin dashboard to a
Google Sheet ("Voya Bookings Live") over a small HTTP API.

Deployed on Render (or any host) using environment variables for Google
OAuth credentials — no secret files are committed to this repo.

Required environment variables:
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REFRESH_TOKEN
  GOOGLE_SHEET_ID       (the spreadsheet id from its URL)

Endpoints:
  GET  /api/bookings   -> JSON array of bookings (newest first)
  POST /api/bookings   -> append one booking (JSON body)
  GET  /api/tours      -> JSON array of visible tours from the catalog sheet
  GET  /healthz        -> simple health check
"""
import json
import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
HEADERS = ["booking_id", "tour", "pax", "pickup", "date", "status", "sla",
           "sla_level", "customer", "need", "next_action", "log", "created_at"]
DATA_RANGE = "Sheet1!A2:M2000"
APPEND_RANGE = "Sheet1!A:M"

# ── Voya Tour Catalog (Google Sheets as the tour database) ──
# Columns: id, name, category, price, rating, reviews, image, desc,
#          visible, hero, sort  (extra columns are ignored — safe to add more later)
TOUR_SHEET_ID = os.environ.get("GOOGLE_TOUR_SHEET_ID", SHEET_ID)
TOUR_HEADERS = ["id", "name", "category", "price", "rating", "reviews",
                "image", "desc", "visible", "hero", "sort"]
TOUR_RANGE = "Tours!A2:K2000"


def get_sheets_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.get("/api/bookings")
def list_bookings():
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=DATA_RANGE
    ).execute()
    rows = result.get("values", [])
    bookings = []
    for row in rows:
        if not row or not row[0]:
            continue
        padded = row + [""] * (len(HEADERS) - len(row))
        record = dict(zip(HEADERS, padded))
        record["log"] = [l for l in record.get("log", "").split("\n") if l]
        bookings.append(record)
    bookings.reverse()
    return jsonify(bookings)


@app.post("/api/bookings")
def create_booking():
    payload = request.get_json(force=True, silent=True) or {}
    row = [
        payload.get("booking_id", ""),
        payload.get("tour", ""),
        payload.get("pax", ""),
        payload.get("pickup", ""),
        payload.get("date", ""),
        payload.get("status", "new"),
        payload.get("sla", ""),
        payload.get("sla_level", "warn"),
        payload.get("customer", ""),
        payload.get("need", ""),
        payload.get("next_action", ""),
        "\n".join(payload.get("log", [])) if isinstance(payload.get("log"), list) else payload.get("log", ""),
        payload.get("created_at", ""),
    ]
    service = get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=APPEND_RANGE,
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()
    return jsonify({"status": "created"}), 201


@app.patch("/api/bookings/<booking_id>")
def update_booking(booking_id):
    payload = request.get_json(force=True, silent=True) or {}
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=DATA_RANGE
    ).execute()
    rows = result.get("values", [])
    for idx, row in enumerate(rows):
        if row and row[0] == booking_id:
            padded = row + [""] * (len(HEADERS) - len(row))
            record = dict(zip(HEADERS, padded))
            existing_log = record.get("log", "")
            record.update({k: v for k, v in payload.items() if k in HEADERS and k != "log"})
            if "log" in payload:
                new_line = payload["log"] if isinstance(payload["log"], str) else "\n".join(payload["log"])
                record["log"] = (existing_log + "\n" + new_line).strip("\n") if existing_log else new_line
            new_row = [record.get(h, "") for h in HEADERS]
            sheet_row_number = idx + 2  # +2: header row + 1-index
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"Sheet1!A{sheet_row_number}:M{sheet_row_number}",
                valueInputOption="RAW",
                body={"values": [new_row]},
            ).execute()
            return jsonify({"status": "updated", "booking_id": booking_id})
    return jsonify({"error": "booking_id not found"}), 404


@app.get("/api/tours")
def list_tours():
    """Read the tour catalog from the Google Sheet (Voya Tour Catalog)."""
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=TOUR_SHEET_ID, range=TOUR_RANGE
        ).execute()
    except Exception as exc:  # sheet unreachable / bad id / auth failure
        app.logger.error(
            "GET /api/tours failed to read sheet %s range %s: %s",
            TOUR_SHEET_ID, TOUR_RANGE, exc,
        )
        return jsonify({
            "error": "tour catalog unavailable",
            "detail": str(exc),
        }), 500
    rows = result.get("values", [])
    tours = []
    for row in rows:
        if not row or not row[0]:
            continue
        padded = row + [""] * (len(TOUR_HEADERS) - len(row))
        record = dict(zip(TOUR_HEADERS, padded))
        # คอลัมน์ visible: เฉพาะ TRUE เท่านั้นที่แสดง (ค่าว่าง = แสดงตามเดิม)
        vis = str(record.get("visible", "")).strip().upper()
        if vis == "FALSE":
            continue
        # แปลงตัวเลขให้เป็นค่าเดิม (rating/reviews/sort)
        try:
            record["rating"] = float(record["rating"]) if record["rating"] else 0
        except ValueError:
            record["rating"] = 0
        try:
            record["reviews"] = int(float(record["reviews"])) if record["reviews"] else 0
        except ValueError:
            record["reviews"] = 0
        tours.append(record)
    return jsonify(tours)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    app.run(host="0.0.0.0", port=port)
