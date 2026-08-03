"""
Troca o link antigo (rlk0808-lab.github.io/ml-deals) pelo dominio proprio
(caiudeverdade.com.br) na DESCRICAO de cada canal/grupo do Telegram -
so troca o texto do link, preserva o resto da descricao como esta. Se o
link antigo nao aparecer na descricao (ja foi trocado, ou nunca
existiu), nao mexe em nada.

Uso: python atualizar_descricao_telegram.py
"""

import json
import os
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

LINK_ANTIGO = "rlk0808-lab.github.io/ml-deals"
LINK_NOVO = "caiudeverdade.com.br"


def main() -> int:
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    ok_geral = True
    for nicho, cfg in todos.items():
        chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
        if not chat:
            continue

        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChat",
                         params={"chat_id": chat}, timeout=20)
        if r.status_code != 200:
            print(f"[descricao] {nicho}: falha ao ler ({r.status_code}) {r.text[:150]}")
            ok_geral = False
            continue

        descricao = r.json().get("result", {}).get("description", "") or ""
        if LINK_ANTIGO not in descricao:
            print(f"[descricao] {nicho}: sem link antigo na descrição - nada a trocar")
            continue

        nova_descricao = descricao.replace(LINK_ANTIGO, LINK_NOVO)
        r2 = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setChatDescription",
                           json={"chat_id": chat, "description": nova_descricao}, timeout=20)
        ok = r2.status_code == 200
        ok_geral = ok_geral and ok
        print(f"[descricao] {nicho}: {'trocado' if ok else 'FALHOU'} ({r2.status_code}) "
              f"{r2.text[:150] if not ok else ''}")

    return 0 if ok_geral else 1


if __name__ == "__main__":
    raise SystemExit(main())
