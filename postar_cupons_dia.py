"""
Broadcast manual - manda UM post juntando varios cupons gerais da
plataforma (nao amarrados a nicho especifico) pra TODOS os canais do
Telegram de uma vez. Diferente do fluxo normal de cupons.py (1 cupom =
1 post, direcionado a 1 nicho), isso e pra cupons "use em qualquer
coisa" que valem a pena divulgar pra todo mundo junto.

O texto do post fica no proprio script (editado a cada vez que o
Robson colar um novo lote de cupons) - nao tenta parsear formato livre
automaticamente, e mais confiavel escrever a mensagem final aqui.

Uso: python postar_cupons_dia.py
"""

import json
import os
import sys
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

TEXTO = """🎟️ CUPONS MERCADO LIVRE DE HOJE

CORREAQUIHJ — 10% OFF, até R$ 1000 de desconto (mín. R$ 79) — https://bit.ly/4wsj3Gh — só hoje

DESCONTODOML — 20% OFF (mín. R$ 79) — https://bit.ly/4pGnXwJ — até 02/08

CUPOMNOML — 22% OFF (mín. R$ 29) — https://bit.ly/4fq6uoQ — até 02/08

OFERTAS — 25% OFF (mín. R$ 29) — https://bit.ly/4wkj7aY — até 02/08

MELIACHA — 22% OFF (mín. R$ 29) — https://bit.ly/3THEuVf — até 02/08

QUEROPROMO — 25% OFF (mín. R$ 29) — https://bit.ly/4fnMxz1 — até 02/08

QUEROPROMOML — 20% OFF, até R$ 150 de desconto (mín. R$ 19) — categoria Comércio e Indústria — até 07/08

CUPOMDOMELI — 20% OFF, até R$ 150 de desconto (mín. R$ 19) — categoria Acessórios para veículos — até 07/08

ECONOMIZE — 20% OFF, até R$ 150 de desconto (mín. R$ 19) — categoria Entretenimento — até 07/08

MIMOPARAVOCE — 20% OFF, até R$ 150 de desconto (mín. R$ 19) — categoria Esportes — até 07/08

CORREAQUI — 20% OFF, até R$ 150 de desconto (mín. R$ 19) — categoria Saúde — até 07/08

São cupons gerais da plataforma, em produtos selecionados - nem tudo aceita. \
A gente testou aqui: não pegou num livro, pegou certinho num copo. Vale a \
pena tentar aplicar no carrinho antes de fechar a compra.

📊 Lembre sempre de comparar com o histórico de preço antes de decidir - \
cupom bom é o que cai em cima de um preço que já valia a pena."""


def main() -> int:
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    ok_geral = True
    for nicho, cfg in todos.items():
        chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
        if not chat:
            print(f"[cupons-dia] {nicho}: {cfg['telegram_chat_env']} nao configurado - pulando")
            ok_geral = False
            continue
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat, "text": TEXTO, "disable_web_page_preview": True},
            timeout=20)
        ok = r.status_code == 200
        ok_geral = ok_geral and ok
        # guarda chat_id + message_id no log - sem isso, nao da pra
        # apagar a mensagem depois se algo sair errado (API do Telegram
        # nao lista mensagens antigas do bot, so o que foi anotado na hora)
        msg_id = r.json().get("result", {}).get("message_id") if ok else None
        print(f"[cupons-dia] {nicho}: {'enviado' if ok else 'FALHOU'} ({r.status_code}) "
              f"chat_id={chat} message_id={msg_id}")

    return 0 if ok_geral else 1


if __name__ == "__main__":
    sys.exit(main())
