"""
Coletor de precos do Mercado Livre.
Roda diariamente via GitHub Actions, grava historico em data/historico.csv
e detecta ofertas reais comparando com o proprio historico.
"""

import os
import sys
import csv
import json
import time
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

APP_ID = os.environ.get("ML_APP_ID", "").strip()
APP_SECRET = os.environ.get("ML_APP_SECRET", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Tag de afiliado do ML (preencher depois que a aprovacao sair)
AFFILIATE_TAG = os.environ.get("ML_AFFILIATE_TAG", "").strip()

SITE = "MLB"  # Brasil
API = "https://api.mercadolibre.com"

DATA_DIR = Path("data")
HIST_FILE = DATA_DIR / "historico.csv"
STATE_FILE = DATA_DIR / "ultimo_alerta.json"

# Buscas que vamos monitorar. Comecamos amplo em suspense/thriller.
QUERIES = [
    "livro suspense",
    "livro thriller psicologico",
    "livro misterio policial",
    "freida mcfadden livro",
    "harlan coben livro",
    "dan brown livro",
    "riley sager livro",
    "agatha christie livro",
    "stephen king livro",
    "gillian flynn livro",
]

ITEMS_PER_QUERY = 50          # ML pagina de 50 em 50
MIN_HISTORY_DAYS = 14         # abaixo disso nao confiamos em "oferta"
DEAL_DROP_THRESHOLD = 0.85    # preco atual <= 85% da mediana historica
MIN_SELLER_REPUTATION = {"green", "light_green"}

# ----------------------------------------------------------------------
# AUTH
# ----------------------------------------------------------------------

def get_token() -> str | None:
    """Token de aplicacao via client_credentials (nao exige login de usuario)."""
    if not (APP_ID and APP_SECRET):
        print("[auth] ML_APP_ID/ML_APP_SECRET ausentes -> tentando sem token")
        return None

    try:
        r = requests.post(
            f"{API}/oauth/token",
            headers={"Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": APP_ID,
                "client_secret": APP_SECRET,
            },
            timeout=30,
        )
        if r.status_code == 200:
            print("[auth] token obtido")
            return r.json().get("access_token")
        print(f"[auth] falhou {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[auth] erro: {e}")
    return None


# ----------------------------------------------------------------------
# COLETA
# ----------------------------------------------------------------------

def search(query: str, token: str | None) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = {
        "q": query,
        "limit": ITEMS_PER_QUERY,
        "condition": "new",          # SO livro novo
    }
    try:
        r = requests.get(f"{API}/sites/{SITE}/search",
                         headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[busca] '{query}' -> HTTP {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("results", [])
    except Exception as e:
        print(f"[busca] '{query}' erro: {e}")
        return []


def normalize(item: dict, query: str) -> dict | None:
    """Extrai so o que interessa. Descarta o que nao serve."""
    price = item.get("price")
    if not price or price <= 0:
        return None

    # so produto novo
    if item.get("condition") != "new":
        return None

    seller = item.get("seller") or {}
    rep = (seller.get("seller_reputation") or {}).get("power_seller_status")
    level = (seller.get("seller_reputation") or {}).get("level_id") or ""

    return {
        "data": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "item_id": item.get("id", ""),
        "titulo": (item.get("title") or "").replace(";", ",")[:150],
        "preco": round(float(price), 2),
        "preco_original": item.get("original_price") or "",
        "permalink": item.get("permalink", ""),
        "vendedor_id": seller.get("id", ""),
        "vendedor_nivel": level,
        "vendedor_status": rep or "",
        "vendidos": item.get("sold_quantity", 0),
        "frete_gratis": (item.get("shipping") or {}).get("free_shipping", False),
        "query": query,
    }


def coletar(token: str | None) -> list[dict]:
    linhas = []
    vistos = set()
    for q in QUERIES:
        results = search(q, token)
        print(f"[busca] '{q}' -> {len(results)} resultados")
        for it in results:
            row = normalize(it, q)
            if row and row["item_id"] not in vistos:
                vistos.add(row["item_id"])
                linhas.append(row)
        time.sleep(0.5)  # gentil com a API
    print(f"[coleta] {len(linhas)} itens unicos")
    return linhas


# ----------------------------------------------------------------------
# HISTORICO
# ----------------------------------------------------------------------

CAMPOS = ["data", "item_id", "titulo", "preco", "preco_original", "permalink",
          "vendedor_id", "vendedor_nivel", "vendedor_status", "vendidos",
          "frete_gratis", "query"]


def salvar(linhas: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    novo = not HIST_FILE.exists()
    with HIST_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerows(linhas)
    print(f"[hist] +{len(linhas)} linhas em {HIST_FILE}")


def carregar_historico() -> dict[str, list[dict]]:
    """Agrupa historico por item_id."""
    if not HIST_FILE.exists():
        return {}
    por_item: dict[str, list[dict]] = {}
    with HIST_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            por_item.setdefault(row["item_id"], []).append(row)
    return por_item


# ----------------------------------------------------------------------
# DETECCAO DE OFERTA  <-- o coracao do sistema
# ----------------------------------------------------------------------

def detectar_ofertas(hoje: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    """
    Uma oferta REAL e aquela em que o preco de hoje esta significativamente
    abaixo da MEDIANA do proprio historico do item. Isso ignora o
    'de/por' inflado que as lojas anunciam.
    """
    ofertas = []
    for item in hoje:
        registros = hist.get(item["item_id"], [])

        # dias distintos observados
        dias = {r["data"] for r in registros}
        if len(dias) < MIN_HISTORY_DAYS:
            continue  # historico curto demais -> nao da pra afirmar nada

        precos = []
        for r in registros:
            try:
                precos.append(float(r["preco"]))
            except (ValueError, TypeError):
                pass
        if len(precos) < MIN_HISTORY_DAYS:
            continue

        mediana = statistics.median(precos)
        minimo = min(precos)
        atual = item["preco"]

        if mediana <= 0:
            continue

        # criterio 1: caiu bem abaixo da mediana historica
        if atual > mediana * DEAL_DROP_THRESHOLD:
            continue

        # criterio 2: vendedor confiavel
        if item["vendedor_status"] and item["vendedor_status"] not in MIN_SELLER_REPUTATION:
            continue

        desconto = (1 - atual / mediana) * 100
        item = dict(item)
        item["mediana_hist"] = round(mediana, 2)
        item["minimo_hist"] = round(minimo, 2)
        item["desconto_real"] = round(desconto, 1)
        item["menor_de_todos"] = atual <= minimo
        ofertas.append(item)

    ofertas.sort(key=lambda x: x["desconto_real"], reverse=True)
    print(f"[ofertas] {len(ofertas)} ofertas reais detectadas")
    return ofertas


# ----------------------------------------------------------------------
# PUBLICACAO
# ----------------------------------------------------------------------

def link_afiliado(permalink: str) -> str:
    if AFFILIATE_TAG and permalink:
        sep = "&" if "?" in permalink else "?"
        return f"{permalink}{sep}{AFFILIATE_TAG}"
    return permalink


def montar_msg(o: dict) -> str:
    selo = "🔥 MENOR PREÇO JÁ VISTO" if o["menor_de_todos"] else "📉 QUEDA DE PREÇO"
    frete = "\n🚚 Frete grátis" if o["frete_gratis"] else ""
    return (
        f"{selo}\n\n"
        f"📚 {o['titulo']}\n\n"
        f"💰 R$ {o['preco']:.2f}\n"
        f"📊 Preço normal: R$ {o['mediana_hist']:.2f}\n"
        f"✅ {o['desconto_real']:.0f}% abaixo do habitual"
        f"{frete}\n\n"
        f"🔗 {link_afiliado(o['permalink'])}"
    )


def enviar_telegram(ofertas: list[dict], limite: int = 5) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[telegram] nao configurado - pulando envio")
        return
    for o in ofertas[:limite]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID,
                      "text": montar_msg(o),
                      "disable_web_page_preview": False},
                timeout=20,
            )
            print(f"[telegram] {o['titulo'][:40]} -> {r.status_code}")
            time.sleep(1)
        except Exception as e:
            print(f"[telegram] erro: {e}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print(f"Coletor ML - {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 60)

    token = get_token()
    hoje = coletar(token)

    if not hoje:
        print("[!] Nada coletado. Verifique credenciais / resposta da API acima.")
        return 1

    hist = carregar_historico()
    salvar(hoje)

    dias_hist = len({r["data"] for rs in hist.values() for r in rs})
    print(f"[hist] {dias_hist} dia(s) de historico acumulado "
          f"(precisamos de {MIN_HISTORY_DAYS} para detectar ofertas)")

    ofertas = detectar_ofertas(hoje, hist)

    if ofertas:
        DATA_DIR.mkdir(exist_ok=True)
        with (DATA_DIR / "ofertas_hoje.json").open("w", encoding="utf-8") as f:
            json.dump(ofertas, f, ensure_ascii=False, indent=2)
        for o in ofertas[:10]:
            print(f"  -> R${o['preco']:.2f} ({o['desconto_real']:.0f}% off) "
                  f"{o['titulo'][:55]}")
        enviar_telegram(ofertas)
    else:
        print("[ofertas] nenhuma hoje (normal enquanto o historico esta curto)")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
