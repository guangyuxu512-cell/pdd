from pathlib import Path
import os
import sys

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LOG_DIR = ROOT / ".runlogs"
LOG_DIR.mkdir(exist_ok=True)

os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

uvicorn.run("app.main:app", host="127.0.0.1", port=8800, log_level="info")
