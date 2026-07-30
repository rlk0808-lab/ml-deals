"""
Diagnostico manual do bot do Telegram - mostra o @usuario do bot
(getMe) e as mensagens recentes recebidas por ele (getUpdates), util
pra descobrir o chat_id de uma conversa privada nova (ex: quando o
Robson manda uma mensagem pro bot pela primeira vez).

Uso: python telegram_diagnostico.py
"""

import os

import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()


def main() -> int:
    if not TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=20)
    print("getMe:", r.json())

    r2 = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=20)
    dados = r2.json()
    print(f"\n{len(dados.get('result', []))} atualizacao(oes) recente(s):")
    for u in dados.get("result", []):
        msg = u.get("message", {})
        chat = msg.get("chat", {})
        print(f"- chat_id={chat.get('id')} | tipo={chat.get('type')} | "
              f"nome={chat.get('first_name', chat.get('title', '?'))} | "
              f"texto={msg.get('text', '')!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
