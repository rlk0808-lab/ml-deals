"""
Apaga posts especificos do Instagram (por ID) via Graph API. So roda
com IDs passados explicitamente - nao varre nem decide sozinho o que
apagar, isso e decisao humana (ver listar_posts.py pra revisar antes).

Uso: python apagar_posts.py <id1,id2,id3,...>
"""

import sys

import requests

import publicar_meta as pm


def apagar(media_id: str) -> bool:
    r = requests.delete(
        f"{pm.GRAPH_API}/{media_id}",
        params={"access_token": pm.PAGE_ACCESS_TOKEN},
        timeout=20,
    )
    ok = r.status_code == 200 and r.json().get("success") is True
    print(f"- {media_id}: {'apagado' if ok else 'FALHOU'} "
          f"({r.status_code}) {r.text[:300]}")
    return ok


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python apagar_posts.py <id1,id2,...>")
        return 1
    if not pm.PAGE_ACCESS_TOKEN:
        print("[!] META_PAGE_ACCESS_TOKEN nao configurado")
        return 1
    ids = [i.strip() for i in sys.argv[1].split(",") if i.strip()]
    resultados = [apagar(i) for i in ids]
    print(f"\n{sum(resultados)}/{len(resultados)} apagados com sucesso")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
