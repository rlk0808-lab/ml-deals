"""
Resumo dos proximos destaques da fila, mandado direto no privado do
Telegram do Robson (nao nos canais publicos) - pra ele copiar e colar
nos 4 grupos do WhatsApp, sem precisar reescrever nada na mao.

Por que isso e "espiar" a fila em vez de gerar conteudo novo:
A fila de publicacao (data/{nicho}/fila_publicacao.json) ja vem
diversificada e priorizada pelo coletor (produto com link primeiro,
sem repetir tipo). Espiar o topo dela pega exatamente os mesmos
destaques que o Telegram vai publicar nas proximas horas - sem
precisar de nenhuma logica de selecao nova, e sem tirar nada da fila
(o Telegram publica esses mesmos itens normalmente, no ritmo dele).

Roda 4x por dia (definido no cron-job.org, nao aqui). Cada rodada manda
4 mensagens separadas pro Telegram privado do Robson - uma por nicho -
pra ele poder copiar cada uma pro grupo certo do WhatsApp sem precisar
recortar um texto grande em pedacos.

Uso: python resumo_whatsapp.py
"""

import json
import os
import sys
from pathlib import Path

import requests

import publish_next as pub

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ADMIN = os.environ.get("TELEGRAM_CHAT_ADMIN", "").strip()

QUANTIDADE_POR_RESUMO = 3


def gerar_resumo(nicho: str, cfg: dict) -> str | None:
    fila_path = Path("data") / nicho / "fila_publicacao.json"
    try:
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None

    itens = fila[:QUANTIDADE_POR_RESUMO]
    if not itens:
        return None

    blocos = [pub.montar_mensagem(item, cfg) for item in itens]

    cabecalho = f"📋 RESUMO {cfg['emoji']} {cfg['nome'].upper()} - cole no grupo do WhatsApp\n"
    separador = "\n\n➖➖➖➖➖\n\n"
    return cabecalho + "\n\n" + separador.join(blocos)


def enviar_para_robson(texto: str) -> bool:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ADMIN):
        print("[resumo] TELEGRAM_CHAT_ADMIN nao configurado - "
              "resumo so aparece no log")
        print(texto)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ADMIN, "text": texto,
                  "disable_web_page_preview": True},
            timeout=20)
        return r.status_code == 200
    except requests.RequestException as e:
        print(f"[resumo] falha ao enviar: {e}")
        return False


def main() -> int:
    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))

    enviados = 0
    for nicho, cfg in todos.items():
        texto = gerar_resumo(nicho, cfg)
        if not texto:
            print(f"[resumo] {nicho}: fila vazia, pulando")
            continue

        ok = enviar_para_robson(texto)
        print(f"[resumo] {nicho}: {'enviado' if ok else 'FALHOU'}")
        if ok:
            enviados += 1

    print(f"[resumo] {enviados}/{len(todos)} resumo(s) enviado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
