"""
Coletor de ofertas - Mercado Livre (API de CATALOGO)

Rastreia PRODUTOS (id estavel do catalogo), nao anuncios.
Todo dia consulta TODOS os vendedores de cada produto e fica com o menor
preco novo. Anuncio novo entra sozinho; anuncio morto sai sozinho.

Detecta oferta REAL comparando com a mediana do proprio historico -
ignora completamente o "de/por" inflado das lojas.
"""

import os
import sys
import csv
import json
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
AFFILIATE_TAG = os.environ.get("ML_AFFILIATE_TAG", "").strip()

API = "https://api.mercadolibre.com"
SITE = "MLB"

DATA = Path("data")
WATCHLIST = DATA / "watchlist.json"
HIST = DATA / "historico.csv"
OFERTAS = DATA / "ofertas_hoje.json"

# Termos de descoberta
QUERIES = [
    "harlan coben livro",
    "freida mcfadden livro",
    "dan brown livro",
    "riley sager livro",
    "gillian flynn livro",
    "agatha christie livro",
    "stephen king livro",
    "livro suspense thriller",
    "livro misterio policial",
    "livro thriller psicologico",
    "arthur conan doyle sherlock",
    "colleen hoover livro",
]

MAX_WATCHLIST = 400        # teto para nao estourar rate limit
MIN_DIAS_HIST = 14         # historico minimo antes de afirmar "oferta"
LIMIAR_QUEDA = 0.85        # preco <= 85% da mediana historica
PAUSA = 0.35               # segundos entre chamadas


# ----------------------------------------------------------------------
# AUTH
# ----------------------------------------------------------------------

def get_token() -> str:
    r = requests.post(
        f"{API}/oauth/token",
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials",
              "client_id": APP_ID, "client_secret": APP_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    print("[auth] token OK")
    return r.json()["access_token"]


def GET(url: str, tk: str, params: dict | None = None):
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {tk}"},
                         params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


# ----------------------------------------------------------------------
# 1. DESCOBERTA  -> encontra PRODUTOS do catalogo por palavra-chave
# ----------------------------------------------------------------------

def carregar_watchlist() -> dict:
    if WATCHLIST.exists():
        return json.loads(WATCHLIST.read_text(encoding="utf-8"))
    return {}


def salvar_watchlist(wl: dict) -> None:
    DATA.mkdir(exist_ok=True)
    WATCHLIST.write_text(json.dumps(wl, ensure_ascii=False, indent=2),
                         encoding="utf-8")


def descobrir(tk: str, wl: dict) -> dict:
    novos = 0
    for q in QUERIES:
        if len(wl) >= MAX_WATCHLIST:
            break
        for offset in (0, 10, 20):          # 3 paginas por termo
            data = GET(f"{API}/products/search", tk,
                       {"site_id": SITE, "q": q, "offset": offset})
            time.sleep(PAUSA)
            if not data:
                break
            results = data.get("results", [])
            if not results:
                break

            for p in results:
                pid = p.get("id")
                if p.get("domain_id") != "MLB-BOOKS":   # so livros
                    continue
                if not pid or pid in wl:
                    continue
                if len(wl) >= MAX_WATCHLIST:
                    break
                wl[pid] = {
                    "nome": (p.get("name") or "")[:180],
                    "permalink": p.get("permalink")
                                 or f"https://www.mercadolivre.com.br/p/{pid}",
                    "query": q,
                    "add": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
                novos += 1
    print(f"[descoberta] +{novos} produtos novos | watchlist: {len(wl)}")
    return wl


# ----------------------------------------------------------------------
# 2. MONITORAMENTO -> menor preco entre TODOS os vendedores do produto
# ----------------------------------------------------------------------

def melhor_oferta(tk: str, pid: str) -> dict | None:
    """Consulta todos os anuncios do produto e devolve o menor preco NOVO."""
    data = GET(f"{API}/products/{pid}/items", tk)
    if not data:
        return None

    ofertas = []
    for it in data.get("results", []):
        if it.get("condition") != "new":       # so livro novo
            continue
        preco = it.get("price")
        if not preco or preco <= 0:
            continue
        ofertas.append({
            "preco": float(preco),
            "item_id": it.get("item_id", ""),
            "seller_id": it.get("seller_id", ""),
            "frete_gratis": bool((it.get("shipping") or {}).get("free_shipping")),
        })

    if not ofertas:
        return None

    melhor = min(ofertas, key=lambda x: x["preco"])
    melhor["n_ofertas"] = len(ofertas)
    return melhor


CAMPOS = ["data", "product_id", "nome", "preco", "n_ofertas",
          "item_id", "seller_id", "frete_gratis", "permalink"]


def coletar(tk: str, wl: dict) -> list[dict]:
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    linhas = []
    for i, (pid, meta) in enumerate(wl.items(), 1):
        m = melhor_oferta(tk, pid)
        time.sleep(PAUSA)
        if not m:
            continue
        linhas.append({
            "data": hoje,
            "product_id": pid,
            "nome": meta["nome"].replace(";", ",").replace("\n", " "),
            "preco": round(m["preco"], 2),
            "n_ofertas": m["n_ofertas"],
            "item_id": m["item_id"],
            "seller_id": m["seller_id"],
            "frete_gratis": m["frete_gratis"],
            "permalink": meta["permalink"],
        })
        if i % 25 == 0:
            print(f"[coleta] {i}/{len(wl)}...")

    print(f"[coleta] {len(linhas)} produtos com preco hoje")
    return linhas


def salvar_hist(linhas: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    novo = not HIST.exists()
    with HIST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerows(linhas)
    print(f"[hist] +{len(linhas)} linhas")


def ler_hist() -> dict[str, list[dict]]:
    if not HIST.exists():
        return {}
    por_prod: dict[str, list[dict]] = {}
    with HIST.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            por_prod.setdefault(row["product_id"], []).append(row)
    return por_prod


# ----------------------------------------------------------------------
# 3. DETECCAO DE OFERTA REAL  <- o coracao do sistema
# ----------------------------------------------------------------------

def detectar(hoje: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    ofertas = []
    for item in hoje:
        regs = hist.get(item["product_id"], [])
        dias = {r["data"] for r in regs}
        if len(dias) < MIN_DIAS_HIST:
            continue

        precos = []
        for r in regs:
            try:
                precos.append(float(r["preco"]))
            except (ValueError, TypeError):
                pass
        if len(precos) < MIN_DIAS_HIST:
            continue

        mediana = statistics.median(precos)
        minimo = min(precos)
        atual = item["preco"]
        if mediana <= 0 or atual > mediana * LIMIAR_QUEDA:
            continue

        o = dict(item)
        o["mediana"] = round(mediana, 2)
        o["minimo_hist"] = round(minimo, 2)
        o["desconto"] = round((1 - atual / mediana) * 100, 1)
        o["recorde"] = atual <= minimo
        ofertas.append(o)

    ofertas.sort(key=lambda x: x["desconto"], reverse=True)
    print(f"[ofertas] {len(ofertas)} ofertas reais")
    return ofertas


# ----------------------------------------------------------------------
# 4. PUBLICACAO
# ----------------------------------------------------------------------

def link(permalink: str) -> str:
    if AFFILIATE_TAG and permalink:
        sep = "&" if "?" in permalink else "?"
        return f"{permalink}{sep}{AFFILIATE_TAG}"
    return permalink


def msg(o: dict) -> str:
    selo = "MENOR PRECO JA REGISTRADO" if o["recorde"] else "QUEDA REAL DE PRECO"
    frete = "\nFrete gratis" if o["frete_gratis"] else ""
    return (
        f"{selo}\n\n"
        f"{o['nome']}\n\n"
        f"Por R$ {o['preco']:.2f}\n"
        f"Preco habitual: R$ {o['mediana']:.2f}\n"
        f"{o['desconto']:.0f}% abaixo do normal"
        f"{frete}\n\n"
        f"{link(o['permalink'])}"
    )


def publicar(ofertas: list[dict], limite: int = 5) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[telegram] nao configurado")
        return
    for o in ofertas[:limite]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg(o)},
                timeout=20)
            print(f"[telegram] {r.status_code} - {o['nome'][:45]}")
            time.sleep(1)
        except Exception as e:
            print(f"[telegram] erro: {e}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main() -> int:
    print("=" * 64)
    print(f"Coletor ML (catalogo) - {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 64)

    if not (APP_ID and APP_SECRET):
        print("[!] Faltam ML_APP_ID / ML_APP_SECRET")
        return 1

    tk = get_token()

    wl = carregar_watchlist()
    wl = descobrir(tk, wl)
    salvar_watchlist(wl)

    if not wl:
        print("[!] Watchlist vazia")
        return 1

    hist = ler_hist()
    hoje = coletar(tk, wl)
    if not hoje:
        print("[!] Nenhum preco coletado")
        return 1

    salvar_hist(hoje)

    dias = len({r["data"] for rs in hist.values() for r in rs})
    print(f"[hist] {dias} dia(s) acumulados (precisa de {MIN_DIAS_HIST})")

    ofertas = detectar(hoje, hist)
    if ofertas:
        DATA.mkdir(exist_ok=True)
        OFERTAS.write_text(json.dumps(ofertas, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        for o in ofertas[:10]:
            print(f"   R${o['preco']:.2f} (-{o['desconto']:.0f}%) {o['nome'][:50]}")
        publicar(ofertas)
    else:
        print("[ofertas] nenhuma hoje - esperado enquanto o historico e curto")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
