"""
Gera um pacote diario de posts prontos pro X (Twitter) e manda por
Telegram pro chat PESSOAL do Robson - X nao tem mais nivel gratuito de
API (fev/2026, US$0,20/post com link), entao a publicacao la e manual:
ele copia o texto e salva a imagem direto do Telegram, sem custo.

Fonte: ofertas.json de cada nicho (mesmos dados que alimentam a
Camada 1) - pega os maiores descontos do dia entre os 4 nichos,
priorizando recorde de menor preco.

Uso: python gerar_fila_x.py
"""

import json
import os
from pathlib import Path

import requests

import image_card
import links_afiliado

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ROBSON = os.environ.get("TELEGRAM_CHAT_ROBSON", "").strip()

QUANTIDADE = 4
LIMITE_X = 280


def _link_afiliado(o: dict) -> str:
    return links_afiliado.resolver(o.get("product_id", ""), o.get("permalink", ""))


def _montar_texto_x(o: dict, cfg: dict) -> str:
    selo = "MENOR PREÇO JÁ REGISTRADO" if o.get("recorde") else "QUEDA REAL DE PREÇO"
    link = _link_afiliado(o)
    preco_linha = f"R$ {o['preco']:.2f} (-{o['desconto']:.0f}%)"

    def montar(nome: str) -> str:
        return f"\U0001F4C9 {selo}\n\n{nome}\n\n{preco_linha}\n\n{link}"

    texto = montar(o["nome"])
    if len(texto) <= LIMITE_X:
        return texto

    sobra_nome = len(o["nome"]) - (len(texto) - LIMITE_X) - 1
    nome_cortado = o["nome"][:max(sobra_nome, 10)] + "…"
    return montar(nome_cortado)


def main() -> int:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ROBSON):
        print("[!] TELEGRAM_TOKEN/TELEGRAM_CHAT_ROBSON nao configurados", flush=True)
        return 1

    # so posts com link de afiliado de verdade - mesma regra do resto
    # do pipeline (SOMENTE_COM_LINK_AFILIADO no collector.py), sem isso
    # o clique nao gera comissao nenhuma
    tabela_links = links_afiliado.carregar()

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    candidatos = []
    for nicho, cfg in todos.items():
        arq = Path("data") / nicho / "ofertas.json"
        if not arq.exists():
            continue
        # ofertas.json nao tem o campo "imagem" (so e buscado na API do
        # ML pros itens que realmente viram post) - o watchlist.json
        # cacheia isso por product_id, reaproveita daqui
        arq_watchlist = Path("data") / nicho / "watchlist.json"
        watchlist = (json.loads(arq_watchlist.read_text(encoding="utf-8"))
                     if arq_watchlist.exists() else {})
        for o in json.loads(arq.read_text(encoding="utf-8")):
            if not links_afiliado.tem_link(o["product_id"], tabela_links):
                continue
            o["imagem"] = watchlist.get(o["product_id"], {}).get("imagem")
            candidatos.append((nicho, cfg, o))

    candidatos.sort(key=lambda t: (not t[2].get("recorde", False), -t[2].get("desconto", 0)))
    escolhidos = candidatos[:QUANTIDADE]

    if not escolhidos:
        print("[fila-x] nenhum candidato disponivel hoje", flush=True)
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ROBSON,
                      "text": "\U0001F4CB Fila do X de hoje: nenhum achado disponível ainda."},
                timeout=20)
        except requests.RequestException as e:
            print(f"[fila-x] erro de rede ao avisar fila vazia: {e}", flush=True)
        return 0

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ROBSON,
                  "text": f"\U0001F4CB Fila do X de hoje ({len(escolhidos)} posts prontos "
                          f"pra copiar - texto já pronto na legenda de cada imagem):"},
            timeout=20)
    except requests.RequestException as e:
        print(f"[fila-x] erro de rede ao mandar cabecalho: {e}", flush=True)

    for nicho, cfg, o in escolhidos:
        texto = _montar_texto_x(o, cfg)
        try:
            imagem_bytes = image_card.gerar_card_feed_oferta_real(o)
        except Exception:
            imagem_bytes = None

        if imagem_bytes:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ROBSON, "caption": texto[:1024]},
                files={"photo": ("cartao.png", imagem_bytes, "image/png")},
                timeout=30)
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ROBSON, "text": texto},
                timeout=20)
        print(f"[fila-x] {nicho} - {o['nome'][:40]!r} - {r.status_code}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
