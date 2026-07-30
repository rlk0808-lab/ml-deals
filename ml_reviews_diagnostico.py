"""
Diagnostico manual - testa a API de avaliacoes (reviews) do Mercado
Livre com um token de verdade, pra confirmar o formato real da
resposta antes de usar isso pra filtrar produtos de maquiagem (nicho
beleza). Nao mexe em nada, so imprime.

Uso: python ml_reviews_diagnostico.py
"""

import json
import os

import requests

API = "https://api.mercadolibre.com"
APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()

# alguns item_id reais de maquiagem/batom pra testar o formato da resposta
ITENS_TESTE = ["MLB5407566240", "MLB50585712"]


def get_token() -> str:
    r = requests.post(f"{API}/oauth/token",
                       headers={"Accept": "application/json",
                                "Content-Type": "application/x-www-form-urlencoded"},
                       data={"grant_type": "client_credentials",
                             "client_id": APP_ID, "client_secret": APP_SECRET},
                       timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> int:
    if not (APP_ID and APP_SECRET):
        print("[!] ML_APP_ID/ML_APP_SECRET nao configurados")
        return 1

    tk = get_token()
    print("[auth] token OK\n")

    for item_id in ITENS_TESTE:
        print(f"=== GET /reviews/item/{item_id} ===")
        r = requests.get(f"{API}/reviews/item/{item_id}",
                          headers={"Authorization": f"Bearer {tk}"},
                          params={"locale": "pt_BR"}, timeout=20)
        print(f"status: {r.status_code}")
        try:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:1500])
        except Exception:
            print(r.text[:500])
        print()

        # tambem testa buscando por produto de maquiagem de verdade via search
    print("=== busca de teste: 'batom' (pra achar item_id real de maquiagem) ===")
    r = requests.get(f"{API}/products/search", headers={"Authorization": f"Bearer {tk}"},
                      params={"q": "batom", "site_id": "MLB", "limit": 3}, timeout=20)
    print(f"status: {r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:2000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
