"""Shared mutable state and constants — imported by all modules."""
from pathlib import Path
from flask import Flask

UDP_PORT   = 20777
WEB_PORT   = 5000
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "sessions"
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))

collector       = None   # SessionCollector, set in main()
session_context: dict = {}

voice_trigger_ts:   str = ""
voice_stop_ts:      str = ""
analyze_trigger_ts: str = ""
