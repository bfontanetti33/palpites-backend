"""Testa o endpoint de recomendação com a chave real — exibe JSON completo."""
import json, sys, os, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.main import app
from fastapi.testclient import TestClient

TOKEN = os.getenv("PREMIUM_TOKEN", "")
client = TestClient(app, raise_server_exceptions=True)

print("Buscando recomendacao para mexico-south-africa...")
r = client.get(
    "/api/v1/copa/jogos/mexico-south-africa/recomendacao",
    headers={"Authorization": f"Bearer {TOKEN}"},
)
print(f"Status: {r.status_code}\n")
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
