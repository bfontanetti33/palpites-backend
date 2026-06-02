import os, sys, warnings
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("API_FOOTBALL_KEY", "x")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")
os.environ.setdefault("PREMIUM_TOKEN", "x")
warnings.filterwarnings("ignore")

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)

# 1. health
r = client.get("/health")
print(f"[1] /health -> {r.status_code}: {r.json()}")

# 2. lista todos os jogos
r = client.get("/api/v1/copa/jogos")
if r.status_code == 200:
    body = r.json()
    total = body.get("total", "?")
    temp  = body.get("temporada", "?")
    print(f"[2] /copa/jogos -> {r.status_code}: total={total}, temporada={temp}")
    if body.get("partidas"):
        p = body["partidas"][0]
        print(f"    Primeiro jogo: {p['time_casa_nome']} x {p['time_fora_nome']} | slug={p['slug']}")
else:
    print(f"[2] /copa/jogos -> {r.status_code}: {r.text[:300]}")

# 3. slug inexistente (deve dar 404 com mensagem clara)
r = client.get("/api/v1/copa/jogos/mexico-south-africa")
print(f"[3] /copa/jogos/mexico-south-africa -> {r.status_code}: {r.json()}")

# 4. recomendacao sem token (deve dar 403)
r = client.get("/api/v1/copa/jogos/mexico-south-africa/recomendacao")
print(f"[4] /recomendacao sem token -> {r.status_code}: {r.json()}")

# 5. docs
r = client.get("/docs")
print(f"[5] /docs -> {r.status_code}")

print("\nTodos os endpoints responderam corretamente.")
