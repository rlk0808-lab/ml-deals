"""
Lista os posts recentes da Pagina do Facebook e do perfil do Instagram
via Graph API - so leitura, nao apaga nem publica nada. Serve pra
revisar visualmente (com o Robson) quais posts antigos (ex: os "so
foto", de antes do cartao de feed) valem apagar.

Uso: python listar_posts.py
"""

import sys

import requests

import publicar_meta as pm


def listar_facebook(limite: int = 25) -> None:
    print(f"\n=== Facebook (Pagina {pm.PAGE_ID}) ===")
    r = requests.get(
        f"{pm.GRAPH_API}/{pm.PAGE_ID}/feed",
        params={
            "fields": "id,message,created_time,permalink_url",
            "limit": limite,
            "access_token": pm.PAGE_ACCESS_TOKEN,
        },
        timeout=20,
    )
    if r.status_code != 200:
        print(f"[!] falhou ({r.status_code}): {r.text[:300]}")
        return
    dados = r.json().get("data", [])
    print(f"{len(dados)} post(s) encontrados:\n")
    for p in dados:
        msg = (p.get("message") or "").replace("\n", " ")[:80]
        print(f"- id={p['id']} | {p.get('created_time', '?')}")
        print(f"  legenda: {msg or '(sem legenda / so imagem)'}")
        print(f"  link: {p.get('permalink_url', '?')}\n")


def listar_instagram(limite: int = 25) -> None:
    print(f"\n=== Instagram (conta {pm.IG_USER_ID}) ===")
    r = requests.get(
        f"{pm.GRAPH_API}/{pm.IG_USER_ID}/media",
        params={
            "fields": "id,caption,timestamp,permalink,media_product_type",
            "limit": limite,
            "access_token": pm.PAGE_ACCESS_TOKEN,
        },
        timeout=20,
    )
    if r.status_code != 200:
        print(f"[!] falhou ({r.status_code}): {r.text[:300]}")
        return
    dados = r.json().get("data", [])
    print(f"{len(dados)} item(ns) encontrados:\n")
    for p in dados:
        cap = (p.get("caption") or "").replace("\n", " ")[:80]
        print(f"- id={p['id']} | {p.get('media_product_type', '?')} | "
              f"{p.get('timestamp', '?')}")
        print(f"  legenda: {cap or '(sem legenda / so imagem)'}")
        print(f"  link: {p.get('permalink', '?')}\n")


def main() -> int:
    if not (pm.PAGE_ID and pm.PAGE_ACCESS_TOKEN and pm.IG_USER_ID):
        print("[!] variaveis META_PAGE_ID / META_PAGE_ACCESS_TOKEN / "
              "META_IG_USER_ID nao configuradas", flush=True)
        return 1
    listar_facebook()
    listar_instagram()
    return 0


if __name__ == "__main__":
    sys.exit(main())
