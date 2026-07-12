"""
Coletor de ofertas - Mercado Livre (multi-nicho)

Rastreia PRODUTOS do catalogo (id estavel), nunca anuncios.
A cada rodada consulta TODOS os vendedores de cada produto e fica com o
menor preco novo. Anuncio novo entra sozinho; anuncio morto sai sozinho.

Oferta REAL = preco de hoje muito abaixo da MEDIANA do proprio historico.
Ignora o "de/por" inflado das lojas.

Uso:  python collector.py <nicho>
      python collector.py livros
      python collector.py bebes
"""

import os
import sys
import csv
import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.mercadolibre.com"
SITE = "MLB"

APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
AFFILIATE_TAG = os.environ.get("ML_AFFILIATE_TAG", "").strip()

MAX_WATCHLIST = 1200       # por nicho
MIN_DIAS_HIST = 14         # historico minimo antes de afirmar "oferta"
LIMIAR_QUEDA = 0.85        # preco <= 85% da mediana historica
WORKERS = 8                # requisicoes em paralelo
MAX_FALHAS = 10            # apos N rodadas sem oferta, some da watchlist

CAMPOS = ["data", "product_id", "nome", "preco", "n_ofertas",
          "item_id", "seller_id", "frete_gratis", "permalink"]


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------

sess = requests.Session()


def get_token() -> str:
    r = sess.post(
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
    for tentativa in range(3):
        try:
            r = sess.get(url, headers={"Authorization": f"Bearer {tk}"},
                         params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:            # rate limit -> respira
                time.sleep(2 * (tentativa + 1))
                continue
            return None
        except Exception:
            time.sleep(1)
    return None


# ----------------------------------------------------------------------
# DESCOBERTA
# ----------------------------------------------------------------------

def descobrir(tk: str, cfg: dict, wl: dict) -> dict:
    permitidos = set(cfg.get("domains_permitidos") or [])
    bloqueados = set(cfg.get("domains_bloqueados") or [])
    novos = 0

    def busca(args):
        q, off = args
        return GET(f"{API}/products/search", tk,
                   {"site_id": SITE, "q": q, "offset": off})

    tarefas = [(q, off) for q in cfg["queries"] for off in (0, 10, 20, 30)]

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (q, _), data in zip(tarefas, ex.map(busca, tarefas)):
            if not data:
                continue
            for p in data.get("results", []):
                if len(wl) >= MAX_WATCHLIST:
                    break
                pid = p.get("id")
                dom = p.get("domain_id") or ""
                if not pid or pid in wl:
                    continue
                if permitidos and dom not in permitidos:
                    continue
                if dom in bloqueados:
                    continue
                wl[pid] = {
                    "nome": (p.get("name") or "")[:180],
                    "permalink": p.get("permalink")
                                 or f"https://www.mercadolivre.com.br/p/{pid}",
                    "dominio": dom,
                    "query": q,
                    "falhas": 0,
                }
                novos += 1

    print(f"[descoberta] +{novos} novos | watchlist: {len(wl)}")
    return wl


# ----------------------------------------------------------------------
# COLETA
# ----------------------------------------------------------------------

def melhor_preco(tk: str, pid: str, cfg: dict) -> dict | None:
    data = GET(f"{API}/products/{pid}/items", tk)
    if not data:
        return None

    pmin = cfg.get("preco_min", 0)
    pmax = cfg.get("preco_max", 10**9)

    ofertas = []
    for it in data.get("results", []):
        if it.get("condition") != "new":          # so produto novo
            continue
        preco = it.get("price")
        if not preco or not (pmin <= float(preco) <= pmax):
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


def coletar(tk: str, cfg: dict, wl: dict) -> tuple[list[dict], dict]:
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pids = list(wl.keys())

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        resultados = list(ex.map(lambda p: melhor_preco(tk, p, cfg), pids))

    linhas, mortos = [], []
    for pid, m in zip(pids, resultados):
        meta = wl[pid]
        if not m:
            meta["falhas"] = meta.get("falhas", 0) + 1
            if meta["falhas"] >= MAX_FALHAS:
                mortos.append(pid)
            continue
        meta["falhas"] = 0
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

    for pid in mortos:
        wl.pop(pid, None)
    if mortos:
        print(f"[limpeza] {len(mortos)} produtos mortos removidos")

    print(f"[coleta] {len(linhas)}/{len(pids)} produtos com preco")
    return linhas, wl


# ----------------------------------------------------------------------
# DETECCAO
# ----------------------------------------------------------------------

def detectar(hoje: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    ofertas = []
    for item in hoje:
        regs = hist.get(item["product_id"], [])
        if len({r["data"] for r in regs}) < MIN_DIAS_HIST:
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
# PUBLICACAO
# ----------------------------------------------------------------------

def link(url: str) -> str:
    if AFFILIATE_TAG and url:
        return f"{url}{'&' if '?' in url else '?'}{AFFILIATE_TAG}"
    return url


def montar(o: dict, cfg: dict) -> str:
    selo = "MENOR PRECO JA REGISTRADO" if o["recorde"] else "QUEDA REAL DE PRECO"
    frete = "\nFrete gratis" if o["frete_gratis"] else ""
    return (
        f"{cfg['emoji']} {selo}\n\n"
        f"{o['nome']}\n\n"
        f"Por R$ {o['preco']:.2f}\n"
        f"Preco habitual: R$ {o['mediana']:.2f}\n"
        f"{o['desconto']:.0f}% abaixo do normal"
        f"{frete}\n\n"
        f"{link(o['permalink'])}"
    )


def publicar(ofertas: list[dict], cfg: dict, limite: int = 5) -> None:
    chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
    if not (TELEGRAM_TOKEN and chat):
        print(f"[telegram] {cfg['telegram_chat_env']} nao configurado")
        return
    for o in ofertas[:limite]:
        try:
            r = sess.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat, "text": montar(o, cfg)}, timeout=20)
            print(f"[telegram] {r.status_code} - {o['nome'][:45]}")
            time.sleep(1)
        except Exception as e:
            print(f"[telegram] erro: {e}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python collector.py <nicho>")
        return 1
    nicho = sys.argv[1]

    cfg_all = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    if nicho not in cfg_all:
        print(f"[!] nicho '{nicho}' nao existe. Disponiveis: {list(cfg_all)}")
        return 1
    cfg = cfg_all[nicho]

    print("=" * 64)
    print(f"{cfg['emoji']} {cfg['nome']} - {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 64)

    if not (APP_ID and APP_SECRET):
        print("[!] faltam ML_APP_ID / ML_APP_SECRET")
        return 1

    d = Path("data") / nicho
    d.mkdir(parents=True, exist_ok=True)
    f_wl, f_hist, f_of = d / "watchlist.json", d / "historico.csv", d / "ofertas.json"

    # migra historico antigo (que ficava solto em data/) para data/livros/
    if nicho == "livros":
        for antigo, novo in ((Path("data/watchlist.json"), f_wl),
                             (Path("data/historico.csv"), f_hist)):
            if antigo.exists() and not novo.exists():
                antigo.rename(novo)
                print(f"[migracao] {antigo} -> {novo}")

    tk = get_token()

    wl = json.loads(f_wl.read_text(encoding="utf-8")) if f_wl.exists() else {}
    wl = descobrir(tk, cfg, wl)

    hist: dict[str, list[dict]] = {}
    if f_hist.exists():
        with f_hist.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                hist.setdefault(row["product_id"], []).append(row)

    hoje, wl = coletar(tk, cfg, wl)
    f_wl.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")

    if not hoje:
        print("[!] nada coletado")
        return 1

    novo = not f_hist.exists()
    with f_hist.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerows(hoje)
    print(f"[hist] +{len(hoje)} linhas")

    dias = len({r["data"] for rs in hist.values() for r in rs})
    print(f"[hist] {dias} dia(s) acumulados (precisa de {MIN_DIAS_HIST})")

    ofertas = detectar(hoje, hist)
    if ofertas:
        f_of.write_text(json.dumps(ofertas, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        for o in ofertas[:10]:
            print(f"   R${o['preco']:.2f} (-{o['desconto']:.0f}%) {o['nome'][:50]}")
        publicar(ofertas, cfg)
    else:
        print("[ofertas] nenhuma - esperado enquanto o historico e curto")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
