"""Paths and settings. Override with environment variables if needed."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The hackathon data pack's `data/` folder (read-only, never modified).
DATA_DIR = Path(os.environ.get("TAXI_DATA_DIR", PROJECT_ROOT / "data"))

# Our own SQLite database: requests, offers, bookings, change requests.
DB_PATH = Path(os.environ.get("TAXI_DB_PATH", PROJECT_ROOT / "backend" / "taxi.db"))

FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
