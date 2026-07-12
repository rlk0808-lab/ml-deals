"""
SONDA DE DIAGNOSTICO - Mercado Livre API
Testa varios endpoints e reporta quais funcionam e quais estao bloqueados.
Rodar UMA vez, copiar a saida e mandar para analise.
"""

import os
import json
import requests

APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()
API = "https://api.mercadolibre.com"

# Cobaias reais (extraidas de links do proprio ML)
PROD_COBEN = "MLB19243683"   # Um Passo em Falso - Harlan Coben
PROD_HP    = "MLB19784007"   # Box Harry Potter
PROD_VINCI = "MLB49114261"   # O Codigo Da Vinci
ITEM_COBEN = "MLB5042354546" # anuncio vencedor do Coben
CAT_LIVROS = "MLB1196"       # categoria Livros (a confirmar)


def token() -> str:
    r = requests.post(
        f"{API}/oauth/token",
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials",
              "client_id": APP_ID, "client_secret": APP_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def probe(nome: str, url: str, tk: str, params: dict | None = None) -> None:
    """Testa um endpoint com e sem token."""
    print("\n" + "=" * 70)
    print(f"### {nome}")
    print(f"GET {url}")
    if params:
        print(f"params: {params}")

    for label, headers in [("COM token", {"Authorization": f"Bearer {tk}"}),
                           ("SEM token", {})]:
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            status = r.status_code
            if status == 200:
                data = r.json()
                # resumo curto do que voltou
                if isinstance(data, dict):
                    if "results" in data:
                        n = len(data["results"])
                        print(f"  [{label}] ✅ 200 — {n} resultados")
                        if n:
                            print(f"      amostra: {json.dumps(data['results'][0], ensure_ascii=False)[:300]}")
                    else:
                        chaves = list(data.keys())[:12]
                        print(f"  [{label}] ✅ 200 — chaves: {chaves}")
                        for k in ("name", "title", "price", "buy_box_winner", "status"):
                            if k in data:
                                v = json.dumps(data[k], ensure_ascii=False)[:200]
                                print(f"      {k}: {v}")
                elif isinstance(data, list):
                    print(f"  [{label}] ✅ 200 — lista com {len(data)} itens")
                    if data:
                        print(f"      amostra: {json.dumps(data[0], ensure_ascii=False)[:300]}")
            else:
                print(f"  [{label}] ❌ {status} — {r.text[:160]}")
        except Exception as e:
            print(f"  [{label}] 💥 erro: {e}")


def main() -> None:
    print("SONDA DE ENDPOINTS - MERCADO LIVRE")
    tk = token()
    print(f"token OK ({len(tk)} chars)")

    # --- 1. CATALOGO (o que realmente queremos) ---
    probe("PRODUTO de catalogo (Coben)",
          f"{API}/products/{PROD_COBEN}", tk)

    probe("ANUNCIOS de um produto de catalogo",
          f"{API}/products/{PROD_COBEN}/items", tk)

    probe("PRODUTO de catalogo (Da Vinci)",
          f"{API}/products/{PROD_VINCI}", tk)

    # --- 2. BUSCA DE PRODUTOS DE CATALOGO (descoberta!) ---
    probe("BUSCA de produtos no catalogo",
          f"{API}/products/search", tk,
          {"site_id": "MLB", "q": "harlan coben livro"})

    probe("BUSCA de produtos por status",
          f"{API}/products/search", tk,
          {"site_id": "MLB", "status": "active", "q": "livro suspense"})

    # --- 3. ITENS (sabemos que /items?ids= funciona) ---
    probe("ITEM por id (anuncio)",
          f"{API}/items", tk, {"ids": ITEM_COBEN})

    probe("MULTIGET de varios itens",
          f"{API}/items", tk,
          {"ids": ITEM_COBEN, "attributes": "id,title,price,permalink,sold_quantity"})

    # --- 4. BUSCA CLASSICA (esperamos 403) ---
    probe("BUSCA classica por palavra-chave (esperado 403)",
          f"{API}/sites/MLB/search", tk, {"q": "livro suspense", "limit": 5})

    probe("BUSCA classica por categoria (esperado 403)",
          f"{API}/sites/MLB/search", tk, {"category": CAT_LIVROS, "limit": 5})

    # --- 5. DESCOBERTA ALTERNATIVA ---
    probe("MAIS VENDIDOS da categoria Livros",
          f"{API}/highlights/MLB/category/{CAT_LIVROS}", tk)

    probe("TENDENCIAS da categoria Livros",
          f"{API}/trends/MLB/{CAT_LIVROS}", tk)

    probe("ARVORE de categorias (achar id certo de Livros)",
          f"{API}/sites/MLB/categories", tk)

    probe("DETALHE da categoria Livros",
          f"{API}/categories/{CAT_LIVROS}", tk)

    print("\n" + "=" * 70)
    print("FIM DA SONDA — copie TODA esta saida e envie para analise")


if __name__ == "__main__":
    main()
