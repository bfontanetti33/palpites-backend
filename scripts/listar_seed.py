import json, sys, os, warnings
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=True)

r = client.get("/api/v1/copa/jogos/mexico-south-africa")
print(f"Status: {r.status_code}\n")
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
