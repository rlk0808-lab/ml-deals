"""
Diagnostico manual - descobre os domain_id reais de categorias de
maquiagem no Mercado Livre (pra configurar o filtro de avaliacao
minima do nicho beleza) e confirma o formato da API de reviews.
Nao mexe em nada, so imprime.

Uso: python ml_reviews_diagnostico.py
"""

import json
import os

import requests

API = "https://api.mercadolibre.com"
APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()

QUERIES_MAQUIAGEM = [
    "batom", "base facial", "sombra maquiagem", "mascara de cilios",
    "delineador", "po compacto", "blush", "corretivo facial",
    "esmalte", "lapis de sobrancelha", "kit maquiagem", "gloss labial",
]


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

    dominios_vistos: dict[str, str] = {}
    for q in QUERIES_MAQUIAGEM:
        r = requests.get(f"{API}/products/search", headers={"Authorization": f"Bearer {tk}"},
                          params={"q": q, "site_id": "MLB", "limit": 5}, timeout=20)
        if r.status_code != 200:
            print(f"[!] busca '{q}' falhou: {r.status_code}")
            continue
        for p in r.json().get("results", []):
            dom = p.get("domain_id")
            if dom and dom not in dominios_vistos:
                dominios_vistos[dom] = p.get("name", "")[:60]

    print("=== domain_id encontrados pras buscas de maquiagem ===")
    for dom, exemplo in sorted(dominios_vistos.items()):
        print(f"{dom}  (ex: {exemplo})")

    print("\n=== confirmando formato da API de reviews (item conhecido) ===")
    r = requests.get(f"{API}/reviews/item/MLB69908674",
                      headers={"Authorization": f"Bearer {tk}"},
                      params={"locale": "pt_BR"}, timeout=20)
    print(f"status: {r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:800])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
