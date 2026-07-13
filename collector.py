"""
Coletor de ofertas - Mercado Livre (multi-nicho)

Rastreia PRODUTOS do catalogo (id estavel), nunca anuncios.
A cada rodada consulta TODOS os vendedores e escolhe a melhor oferta
que passe nos filtros de qualidade.

FILTROS DE QUALIDADE (definidos em config/nichos.json):
  - somente produto NOVO
  - somente moeda BRL, sem importados
  - somente frete gratis ou Mercado Envios Full
  - livros: somente edicao em portugues
  - exclui nome com "usado", "in english", "importado", etc.

Oferta REAL = preco de hoje muito abaixo da MEDIANA do proprio historico.

Uso:  python collector.py livros
      python collector.py bebes
"""

import os
import sys
import csv
import json
import time
import statistics
import unicodedata
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

MAX_WATCHLIST = 1200
MIN_DIAS_HIST = 14
LIMIAR_QUEDA = 0.85
WORKERS = 8
MAX_FALHAS = 10

# Camada 2 - "melhor preco hoje": roda 1x/dia, na primeira rodada (6h BRT = 9h UTC),
# para o canal nao ficar mudo enquanto o historico de 14 dias nao fecha.
HORA_CAMADA2_UTC = 9

# Fila de publicacao: quem posta de verdade e o publish_next.py, a cada 30 min
# (07h-23h30 BRT = 34 disparos/dia). Aqui so decidimos o que ENTRA na fila.
# O dedup por product_id em enfileirar() evita fila crescer sem controle -
# so entra item novo, entao o limite por chamada e so um teto de seguranca.
LIMITE_FILA_CAMADA1 = 34
LIMITE_FILA_CAMADA2 = 34
LIMITE_FILA_FALSO_DESCONTO = 3  # esporadico de proposito - e conteudo de "flagrante", nao de rotina

CAMPOS = ["data", "product_id", "nome", "preco", "n_ofertas", "item_id",
          "seller_id", "frete_gratis", "full", "permalink"]

sess = requests.Session()
_dump_feito = False       # imprime o schema real de 1 anuncio, uma vez


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------

def get_token() -> str:
    r = sess.post(f"{API}/oauth/token",
                  headers={"Accept": "application/json",
                           "Content-Type": "application/x-www-form-urlencoded"},
                  data={"grant_type": "client_credentials",
                        "client_id": APP_ID, "client_secret": APP_SECRET},
                  timeout=30)
    r.raise_for_status()
    print("[auth] token OK")
    return r.json()["access_token"]


def GET(url: str, tk: str, params: dict | None = None):
    for t in range(3):
        try:
            r = sess.get(url, headers={"Authorization": f"Bearer {tk}"},
                         params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 * (t + 1))
                continue
            return None
        except Exception:
            time.sleep(1)
    return None


# ----------------------------------------------------------------------
# FILTROS
# ----------------------------------------------------------------------

def normalizar(txt: str) -> str:
    """minusculas e sem acento, para comparar de forma robusta"""
    txt = (txt or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", txt)
                   if unicodedata.category(c) != "Mn")


def nome_reprovado(nome: str, cfg: dict) -> str | None:
    """Devolve o motivo da reprovacao, ou None se aprovado."""
    n = normalizar(nome)

    for termo in cfg.get("excluir_no_nome", []):
        if normalizar(termo) in n:
            return f"nome contem '{termo}'"

    exigir = cfg.get("exigir_no_nome", [])
    if exigir and not any(normalizar(t) in n for t in exigir):
        return "nao confirma idioma portugues"

    return None


def frete_zero(it: dict) -> bool:
    """
    O campo 'free_shipping' MENTE: vimos anuncio com free_shipping=false
    e shipping.cost=0 (porque e Mercado Envios Full).
    A verdade esta em shipping.cost.
    """
    sh = it.get("shipping") or {}
    custo = sh.get("cost")
    if custo is not None and float(custo) == 0:
        return True
    if sh.get("free_shipping"):
        return True
    if sh.get("logistic_type") == "fulfillment":
        return True
    if "fulfillment" in (sh.get("tags") or []):
        return True
    return False


def eh_full(it: dict) -> bool:
    sh = it.get("shipping") or {}
    return (sh.get("logistic_type") == "fulfillment"
            or "fulfillment" in (sh.get("tags") or []))


def anuncio_reprovado(it: dict, cfg: dict) -> str | None:
    """Aplica os filtros de qualidade sobre UM anuncio."""
    if cfg.get("somente_novo", True) and it.get("condition") != "new":
        return "usado"

    if cfg.get("sem_importados", True):
        if it.get("currency_id") not in (None, "BRL"):
            return "moeda estrangeira"
        idm = it.get("international_delivery_mode")
        if idm not in (None, "none", ""):
            return "importado"

    if cfg.get("exigir_frete_gratis", False):
        if not frete_zero(it):
            return "frete pago"

    preco = it.get("price")
    if not preco:
        return "sem preco"
    if not (cfg.get("preco_min", 0) <= float(preco) <= cfg.get("preco_max", 1e9)):
        return "fora da faixa de preco"

    return None


# ----------------------------------------------------------------------
# DESCOBERTA
# ----------------------------------------------------------------------

def descobrir(tk: str, cfg: dict, wl: dict) -> dict:
    permitidos = set(cfg.get("domains_permitidos") or [])
    bloqueados = set(cfg.get("domains_bloqueados") or [])
    novos = 0
    recusas: dict[str, int] = {}

    tarefas = [(q, off) for q in cfg["queries"] for off in (0, 10, 20, 30)]

    def busca(args):
        q, off = args
        return GET(f"{API}/products/search", tk,
                   {"site_id": SITE, "q": q, "offset": off})

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (q, _), data in zip(tarefas, ex.map(busca, tarefas)):
            if not data:
                continue
            for p in data.get("results", []):
                if len(wl) >= MAX_WATCHLIST:
                    break
                pid = p.get("id")
                dom = p.get("domain_id") or ""
                nome = p.get("name") or ""

                if not pid or pid in wl:
                    continue
                if permitidos and dom not in permitidos:
                    continue
                if dom in bloqueados:
                    continue

                motivo = nome_reprovado(nome, cfg)
                if motivo:
                    recusas[motivo] = recusas.get(motivo, 0) + 1
                    continue

                wl[pid] = {
                    "nome": nome[:180],
                    "permalink": p.get("permalink")
                                 or f"https://www.mercadolivre.com.br/p/{pid}",
                    "dominio": dom,
                    "query": q,
                    "falhas": 0,
                }
                novos += 1

    print(f"[descoberta] +{novos} novos | watchlist: {len(wl)}")
    if recusas:
        print("[descoberta] recusados:", dict(sorted(
            recusas.items(), key=lambda x: -x[1])[:6]))
    return wl


# ----------------------------------------------------------------------
# COLETA
# ----------------------------------------------------------------------

def obter_imagem_produto(tk: str, pid: str) -> str | None:
    """
    Busca a foto oficial do PRODUTO no catalogo (nao do anuncio de um
    vendedor especifico). E estavel - a mesma foto vale pra qualquer
    vendedor daquele produto. So chamamos isso pros poucos itens que
    realmente vao virar post, nunca pra watchlist inteira.
    """
    data = GET(f"{API}/products/{pid}", tk)
    if not data:
        return None
    pics = data.get("pictures") or []
    if not pics:
        return None
    return pics[0].get("url") or pics[0].get("secure_url")


def preparar_imagens(tk: str, itens: list[dict], wl: dict) -> None:
    """Preenche o campo 'imagem' de cada item, usando cache em wl quando existe."""
    for o in itens:
        pid = o["product_id"]
        meta = wl.setdefault(pid, {})
        if "imagem" not in meta:
            meta["imagem"] = obter_imagem_produto(tk, pid) or ""
        o["imagem"] = meta["imagem"] or None


def melhor_oferta(tk: str, pid: str, cfg: dict) -> dict | None:
    global _dump_feito

    data = GET(f"{API}/products/{pid}/items", tk)
    if not data:
        return None

    results = data.get("results", [])

    # imprime o schema real de um anuncio, uma unica vez, para conferencia
    if results and not _dump_feito:
        _dump_feito = True
        print("\n[schema] estrutura real de um anuncio:")
        print(json.dumps(results[0], ensure_ascii=False, indent=2)[:1800])
        print("[schema] fim\n")

    aprovados = []
    for it in results:
        if anuncio_reprovado(it, cfg):
            continue
        op = it.get("original_price")
        aprovados.append({
            "preco": float(it["price"]),
            "preco_original": float(op) if op else None,  # o "de" que a loja anuncia
            "item_id": it.get("item_id", ""),
            "seller_id": it.get("seller_id", ""),
            "frete_gratis": frete_zero(it),
            "full": eh_full(it),
        })

    if not aprovados:
        return None

    # entre os aprovados, o mais barato. Empate -> prefere Full (entrega rapida)
    melhor = min(aprovados, key=lambda x: (x["preco"], not x["full"]))
    melhor["n_ofertas"] = len(aprovados)
    return melhor


def coletar(tk: str, cfg: dict, wl: dict) -> tuple[list[dict], dict]:
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pids = list(wl.keys())

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(lambda p: melhor_oferta(tk, p, cfg), pids))

    linhas, mortos = [], []
    for pid, m in zip(pids, res):
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
            "preco_original": round(m["preco_original"], 2) if m.get("preco_original") else None,
            "n_ofertas": m["n_ofertas"],
            "item_id": m["item_id"],
            "seller_id": m["seller_id"],
            "frete_gratis": m["frete_gratis"],
            "full": m["full"],
            "permalink": meta["permalink"],
        })

    for pid in mortos:
        wl.pop(pid, None)
    if mortos:
        print(f"[limpeza] {len(mortos)} produtos sem oferta valida removidos")

    print(f"[coleta] {len(linhas)}/{len(pids)} produtos com oferta aprovada")
    return linhas, wl


# ----------------------------------------------------------------------
# DETECCAO
# ----------------------------------------------------------------------

def preco_por_dia(regs: list[dict]) -> dict[str, float]:
    """1 preco representativo por dia (o menor do dia). Se usassemos todas
    as linhas cruas, um dia com mais rodadas de coleta pesaria mais que um
    dia com menos rodadas na mediana - e a frequencia de coleta muda ao
    longo do tempo (comecou 4x/dia, pode subir depois). Assim a mediana
    representa "preco normal por dia", nao "por coleta". Usada tanto pela
    deteccao de oferta real quanto pela de falso desconto."""
    por_dia: dict[str, float] = {}
    for r in regs:
        try:
            p = float(r["preco"])
        except (ValueError, TypeError):
            continue
        data = r["data"]
        if data not in por_dia or p < por_dia[data]:
            por_dia[data] = p
    return por_dia


def detectar(hoje: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    ofertas = []
    for item in hoje:
        regs = hist.get(item["product_id"], [])
        if len({r["data"] for r in regs}) < MIN_DIAS_HIST:
            continue

        precos = list(preco_por_dia(regs).values())
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
# FALSO DESCONTO - a loja anuncia queda que nosso historico desmente
# ----------------------------------------------------------------------

MIN_DIAS_FALSO_DESCONTO = 5   # minimo de historico pra poder desmentir com confianca
DESCONTO_ANUNCIADO_MIN = 20.0  # loja precisa anunciar pelo menos isso pra virar "caca"
DESCONTO_REAL_MAX = 8.0        # e o preco de hoje precisa estar perto do normal mesmo

def detectar_falso_desconto(hoje: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    """
    Acha produtos onde a loja anuncia um 'de/por' vistoso, mas o NOSSO
    historico real mostra que o preco de hoje esta perto do normal - ou
    seja, o desconto anunciado nao existe de verdade. Diferente de
    detectar(): aqui nao exigimos os 14 dias completos (MIN_DIAS_HIST),
    porque a alegacao que estamos checando e da PROPRIA LOJA, nao nossa -
    ja com poucos dias de historico da pra desmentir um "de/por" fixo que
    nao mudou. Precisamos so de confianca minima (MIN_DIAS_FALSO_DESCONTO).
    """
    achados = []
    for item in hoje:
        preco_original = item.get("preco_original")
        atual = item["preco"]
        if not preco_original or preco_original <= atual:
            continue  # loja nao anuncia desconto nenhum, nada a checar

        desconto_anunciado = (1 - atual / preco_original) * 100
        if desconto_anunciado < DESCONTO_ANUNCIADO_MIN:
            continue  # desconto pequeno demais pra valer a pena expor

        regs = hist.get(item["product_id"], [])
        precos = list(preco_por_dia(regs).values())
        if len(precos) < MIN_DIAS_FALSO_DESCONTO:
            continue

        mediana = statistics.median(precos)
        if mediana <= 0:
            continue
        desconto_real = (1 - atual / mediana) * 100

        if desconto_real > DESCONTO_REAL_MAX:
            continue  # esse ate que caiu de verdade - nao e "falso desconto"

        o = dict(item)
        o["preco_original"] = round(preco_original, 2)
        o["mediana"] = round(mediana, 2)
        o["desconto_anunciado"] = round(desconto_anunciado, 1)
        o["desconto_real"] = round(desconto_real, 1)
        o["dias_historico"] = len(precos)
        achados.append(o)

    achados.sort(key=lambda x: x["desconto_anunciado"], reverse=True)
    print(f"[falso-desconto] {len(achados)} produto(s) com 'de/por' desmentido pelo histórico")
    return achados


# ----------------------------------------------------------------------
# CAMADA 2 - MELHOR PRECO HOJE (canal nao fica mudo nos 14 dias de historico)
# ----------------------------------------------------------------------

def carregar_contagem_falso_desconto(d: Path) -> dict:
    """Contador que reseta sozinho a cada novo dia UTC - garante que o
    limite diario vale pro DIA, nao so pra uma rodada do coletor."""
    f = d / "falso_desconto_contagem.json"
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if f.exists():
        dados = json.loads(f.read_text(encoding="utf-8"))
        if dados.get("data") == hoje:
            return dados
    return {"data": hoje, "contagem": 0}


def salvar_contagem_falso_desconto(d: Path, dados: dict) -> None:
    (d / "falso_desconto_contagem.json").write_text(
        json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def carregar_estado_camada2(d: Path) -> dict:
    f = d / "camada2_state.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def salvar_estado_camada2(d: Path, estado: dict) -> None:
    f = d / "camada2_state.json"
    f.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def _assinatura_produto(nome: str) -> str:
    """
    Primeira palavra significativa do nome - usada so pra AGRUPAR
    produtos parecidos (ex: varios "jogo de talheres" diferentes),
    nao pra filtrar nada. Ignora palavras genericas tipo kit/jogo/conjunto
    que nao dizem nada sobre o tipo de produto.
    """
    ignorar = {"kit", "jogo", "de", "para", "com", "conjunto", "o", "a",
               "os", "as", "novo", "nova"}
    for p in normalizar(nome).split():
        if p not in ignorar and len(p) > 2:
            return p
    return normalizar(nome)


def detectar_camada2(hoje: list[dict], ja_notificados: set[str],
                      estado: dict) -> list[dict]:
    """
    Melhor preco entre os vendedores, HOJE - nao afirma queda nenhuma,
    so informa o menor preco atual. NUNCA usa a palavra 'oferta' ou 'desconto'.

    Pula produto que:
      - ja disparou Camada 1 hoje (evita duplicar mensagem do mesmo produto)
      - nao mudou de preco/vendedor desde o ultimo post desta camada
        (evita o canal repetir o mesmo post todo dia sem nada de novo)
    """
    candidatos = []
    for item in hoje:
        pid = item["product_id"]
        if pid in ja_notificados:
            continue

        anterior = estado.get(pid)
        if (anterior
                and anterior.get("preco") == item["preco"]
                and anterior.get("seller_id") == item["seller_id"]):
            continue

        candidatos.append(item)

    # prioriza produtos com mais vendedores concorrendo (comparacao mais forte)
    candidatos.sort(key=lambda x: x["n_ofertas"], reverse=True)

    # diversifica por tipo de produto - sem isso, 2 "jogos de talheres"
    # diferentes podiam ocupar 2 das poucas vagas do dia, tirando espaco
    # de variedade. Pega o melhor de CADA tipo antes de repetir um tipo.
    grupos: dict[str, list[dict]] = {}
    for item in candidatos:
        grupos.setdefault(_assinatura_produto(item["nome"]), []).append(item)

    diversificados = []
    indice = 0
    while len(diversificados) < len(candidatos):
        adicionou = False
        for grupo in grupos.values():
            if indice < len(grupo):
                diversificados.append(grupo[indice])
                adicionou = True
        if not adicionou:
            break
        indice += 1

    print(f"[camada2] {len(diversificados)} produtos com preco novo/mudado "
          f"({len(grupos)} tipos diferentes)")
    return diversificados


# ----------------------------------------------------------------------
# PUBLICACAO
# ----------------------------------------------------------------------

def link(url: str) -> str:
    if AFFILIATE_TAG and url:
        return f"{url}{'&' if '?' in url else '?'}{AFFILIATE_TAG}"
    return url


def montar(o: dict, cfg: dict) -> str:
    selo = "MENOR PRECO JA REGISTRADO" if o["recorde"] else "QUEDA REAL DE PRECO"
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} {selo}\n\n"
            f"{o['nome']}\n\n"
            f"Por R$ {o['preco']:.2f}\n"
            f"Preco habitual: R$ {o['mediana']:.2f}\n"
            f"{o['desconto']:.0f}% abaixo do normal"
            f"{entrega}\n\n"
            f"{link(o['permalink'])}")


def montar_camada2(o: dict, cfg: dict) -> str:
    """
    Camada 2: NUNCA afirma queda de preco (nao ha historico suficiente
    ainda para saber se caiu). So informa o melhor preco entre os
    vendedores hoje - e o unico selo honesto possivel neste estagio.
    """
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} MELHOR PRECO ENTRE OS VENDEDORES HOJE\n\n"
            f"{o['nome']}\n\n"
            f"R$ {o['preco']:.2f}\n"
            f"(comparado entre {o['n_ofertas']} vendedores)"
            f"{entrega}\n\n"
            f"{link(o['permalink'])}")


def refrescar_camada2_na_fila(d: Path, hoje: list[dict]) -> int:
    """
    Atualiza os itens de Camada 2 que ainda estao esperando vez na fila
    com o preco coletado AGORA. Roda em toda execucao do coletor (nao so
    na hora da deteccao), entao a fila nunca fica mais desatualizada que
    o intervalo entre rodadas (~4-5h) - a validade de seguranca so entra
    em acao se o produto sumir da coleta (ex: ficou sem estoque).
    """
    fila = carregar_fila(d)
    recentes = {item["product_id"]: item for item in hoje}
    agora = datetime.now(timezone.utc).isoformat()

    atualizados = 0
    for it in fila:
        if it.get("tipo") != "camada2":
            continue
        atual = recentes.get(it["product_id"])
        if not atual:
            continue
        it["preco"] = atual["preco"]
        it["n_ofertas"] = atual["n_ofertas"]
        it["seller_id"] = atual["seller_id"]
        it["permalink"] = atual["permalink"]
        it["full"] = atual["full"]
        it["frete_gratis"] = atual["frete_gratis"]
        it["enfileirado_em"] = agora
        atualizados += 1

    if atualizados:
        salvar_fila(d, fila)
        print(f"[fila] {atualizados} item(ns) de camada2 na fila atualizados "
              f"com preco recente")
    return atualizados


def carregar_fila(d: Path) -> list[dict]:
    f = d / "fila_publicacao.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return []


def salvar_fila(d: Path, fila: list[dict]) -> None:
    f = d / "fila_publicacao.json"
    f.write_text(json.dumps(fila, ensure_ascii=False, indent=2), encoding="utf-8")


def enfileirar(d: Path, itens: list[dict], tipo: str, limite: int) -> int:
    """
    Adiciona itens na fila de publicacao (nao posta na hora - quem posta
    e o publish_next.py, espacado a cada 30 min). Evita duplicar produto
    que ja esta esperando vez na fila.
    """
    fila = carregar_fila(d)
    ja_na_fila = {it["product_id"] for it in fila}
    agora = datetime.now(timezone.utc).isoformat()

    adicionados = 0
    for o in itens:
        if adicionados >= limite:
            break
        if o["product_id"] in ja_na_fila:
            continue
        item = dict(o)
        item["tipo"] = tipo
        item["enfileirado_em"] = agora
        fila.append(item)
        adicionados += 1

    salvar_fila(d, fila)
    print(f"[fila] +{adicionados} item(ns) tipo={tipo} | fila total: {len(fila)}")
    return adicionados


def publicar_lote(itens: list[dict], cfg: dict, montar_func, limite: int) -> None:
    chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
    if not (TELEGRAM_TOKEN and chat):
        print(f"[telegram] {cfg['telegram_chat_env']} nao configurado")
        return
    for o in itens[:limite]:
        texto = montar_func(o, cfg)
        imagem = o.get("imagem")
        try:
            if imagem:
                r = sess.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    json={"chat_id": chat, "photo": imagem,
                          "caption": texto[:1024]}, timeout=20)
                if r.status_code != 200:
                    print(f"[telegram] sendPhoto falhou ({r.status_code}), "
                          f"tentando sem imagem")
                    r = sess.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": chat, "text": texto}, timeout=20)
            else:
                r = sess.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat, "text": texto}, timeout=20)
            print(f"[telegram] {r.status_code} - {o['nome'][:45]}")
            time.sleep(1)
        except Exception as e:
            print(f"[telegram] erro: {e}")


def publicar(ofertas: list[dict], cfg: dict, limite: int = 5) -> None:
    publicar_lote(ofertas, cfg, montar, limite)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python collector.py <nicho>")
        return 1
    nicho = sys.argv[1]

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    if nicho not in todos:
        print(f"[!] nicho '{nicho}' nao existe. Disponiveis: {list(todos)}")
        return 1
    cfg = todos[nicho]

    print("=" * 64)
    print(f"{cfg['emoji']} {cfg['nome']} - {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 64)

    if not (APP_ID and APP_SECRET):
        print("[!] faltam ML_APP_ID / ML_APP_SECRET")
        return 1

    d = Path("data") / nicho
    d.mkdir(parents=True, exist_ok=True)
    f_wl, f_hist, f_of = d / "watchlist.json", d / "historico.csv", d / "ofertas.json"

    # migra o historico antigo (data/*.csv) para data/livros/
    if nicho == "livros":
        for antigo, novo in ((Path("data/watchlist.json"), f_wl),
                             (Path("data/historico.csv"), f_hist)):
            if antigo.exists() and not novo.exists():
                antigo.rename(novo)
                print(f"[migracao] {antigo} -> {novo}")

    tk = get_token()

    wl = json.loads(f_wl.read_text(encoding="utf-8")) if f_wl.exists() else {}

    # remove da watchlist o que nao passa mais nos filtros novos
    antes = len(wl)
    wl = {pid: m for pid, m in wl.items()
          if not nome_reprovado(m.get("nome", ""), cfg)}
    if antes != len(wl):
        print(f"[filtro] {antes - len(wl)} produtos removidos por filtro de nome")

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
        w = csv.DictWriter(fh, fieldnames=CAMPOS, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerows(hoje)
    print(f"[hist] +{len(hoje)} linhas")

    dias = len({r["data"] for rs in hist.values() for r in rs})
    print(f"[hist] {dias} dia(s) acumulados (precisa de {MIN_DIAS_HIST})")

    refrescar_camada2_na_fila(d, hoje)

    ofertas = detectar(hoje, hist)
    if ofertas:
        f_of.write_text(json.dumps(ofertas, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        for o in ofertas[:10]:
            print(f"   R${o['preco']:.2f} (-{o['desconto']:.0f}%) {o['nome'][:50]}")
        preparar_imagens(tk, ofertas[:LIMITE_FILA_CAMADA1], wl)
        enfileirar(d, ofertas, tipo="camada1", limite=LIMITE_FILA_CAMADA1)
    else:
        print("[ofertas] nenhuma - esperado enquanto o historico e curto")

    # Camada 2 - so na primeira rodada do dia, pra nao repetir 4x
    hora_atual = datetime.now(timezone.utc).hour
    forcar_c2 = os.environ.get("FORCAR_CAMADA2", "").strip() == "1"
    if hora_atual == HORA_CAMADA2_UTC or forcar_c2:
        ja_notificados = {o["product_id"] for o in ofertas}
        estado_c2 = carregar_estado_camada2(d)
        candidatos_c2 = detectar_camada2(hoje, ja_notificados, estado_c2)

        if candidatos_c2:
            candidatos_c2 = candidatos_c2[:LIMITE_FILA_CAMADA2]
            for o in candidatos_c2:
                print(f"   [camada2] R${o['preco']:.2f} "
                      f"({o['n_ofertas']} vendedores) {o['nome'][:50]}")
            preparar_imagens(tk, candidatos_c2, wl)
            enfileirar(d, candidatos_c2, tipo="camada2", limite=LIMITE_FILA_CAMADA2)
        else:
            print("[camada2] nada novo pra postar hoje")
    else:
        print(f"[camada2] pulado (roda so as {HORA_CAMADA2_UTC}h UTC "
              f"/ 6h BRT; agora sao {hora_atual}h UTC)")

    # Falso desconto - roda toda rodada (a alegacao pode aparecer a qualquer
    # hora), mas respeita um limite DIARIO baixo de proposito (e conteudo
    # de flagrante, nao de rotina - postar demais banaliza).
    contagem_fd = carregar_contagem_falso_desconto(d)
    restante_fd = max(0, LIMITE_FILA_FALSO_DESCONTO - contagem_fd["contagem"])
    if restante_fd > 0:
        achados_fd = detectar_falso_desconto(hoje, hist)[:restante_fd]
        if achados_fd:
            for o in achados_fd:
                print(f"   [falso-desconto] loja anuncia -{o['desconto_anunciado']:.0f}% "
                      f"mas historico mostra {o['desconto_real']:+.1f}% | {o['nome'][:50]}")
            preparar_imagens(tk, achados_fd, wl)
            adicionados = enfileirar(d, achados_fd, tipo="falso_desconto", limite=restante_fd)
            contagem_fd["contagem"] += adicionados
            salvar_contagem_falso_desconto(d, contagem_fd)
        else:
            print("[falso-desconto] nada encontrado nesta rodada")
    else:
        print(f"[falso-desconto] limite diário ({LIMITE_FILA_FALSO_DESCONTO}) já atingido")

    # imagens buscadas acima ficam em cache no wl - persiste de novo
    f_wl.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
