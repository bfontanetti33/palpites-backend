"""
Adiciona o grupo (A-L) a cada jogo do seed copa_2026.json.
Os grupos são inferidos a partir das partidas da Rodada 1 (Group Stage - 1),
onde cada par de times que se enfrenta pertence ao mesmo grupo.
"""
import json, sys
from pathlib import Path
from itertools import combinations

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEED = Path(__file__).parent.parent / "seeds" / "copa_2026.json"

def main():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    jogos = data["jogos"]

    # Passo 1: identificar grupos via union-find em TODOS os jogos.
    # Em cada grupo de 4 times, qualquer par de times se enfrenta uma vez.
    # Após processar todos os 72 jogos, teremos exatamente 12 grupos de 4.
    parent = {}

    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent.get(root, root)
        # path compression
        while parent.get(x, x) != root:
            nxt = parent.get(x, x)
            parent[x] = root
            x = nxt
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for j in jogos:
        union(j["time_casa"], j["time_fora"])

    r1 = [j for j in jogos if j["rodada_raw"] == "Group Stage - 1"]

    # Mapear cada conjunto de times para uma letra de grupo A-L
    grupos_raw = {}  # root -> set of teams
    for j in jogos:
        for time in [j["time_casa"], j["time_fora"]]:
            root = find(time)
            grupos_raw.setdefault(root, set()).add(time)

    # Ordenar grupos pelo primeiro jogo da rodada 1 (ordem cronológica)
    ordem_grupos = []
    seen_roots = set()
    for j in sorted(r1, key=lambda x: x["data_hora_brasilia"]):
        root = find(j["time_casa"])
        if root not in seen_roots:
            seen_roots.add(root)
            ordem_grupos.append(root)

    letras = "ABCDEFGHIJKL"
    root_para_letra = {root: letras[i] for i, root in enumerate(ordem_grupos)}

    # Passo 2: adicionar campo "grupo" e "rodada" a cada jogo
    for j in jogos:
        root   = find(j["time_casa"])
        letra  = root_para_letra.get(root, "?")
        rodada_num = j["rodada_raw"].replace("Group Stage - ", "")
        j["grupo"]        = f"Grupo {letra}"
        j["rodada"]       = f"Rodada {rodada_num} — Grupo {letra}"
        j["grupo_letra"]  = letra
        j["rodada_numero"] = int(rodada_num) if rodada_num.isdigit() else 0

    # Passo 3: mostrar grupos montados
    grupos_finais = {}
    for root, times in grupos_raw.items():
        letra = root_para_letra.get(root, "?")
        grupos_finais[letra] = sorted(times)

    print("Grupos detectados:")
    for letra in sorted(grupos_finais):
        print(f"  Grupo {letra}: {', '.join(grupos_finais[letra])}")

    # Salva
    data["grupos"] = {f"Grupo {l}": t for l, t in sorted(grupos_finais.items())}
    SEED.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSeed atualizado: {SEED}")

if __name__ == "__main__":
    main()
