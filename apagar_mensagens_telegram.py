"""
Apaga mensagens especificas do Telegram, dado chat_id e message_id -
usado quando algo errado foi publicado (ex: link sem rastreamento de
afiliado) e precisa sumir rapido. So funciona pra mensagens que o
proprio bot enviou (ou tem permissao de admin no chat).

Uso: python apagar_mensagens_telegram.py "<chat_id>:<message_id>,<chat_id>:<message_id>,..."
"""

import os
import sys

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()


def apagar(chat_id: str, message_id: str) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage",
        json={"chat_id": chat_id, "message_id": int(message_id)},
        timeout=20)
    ok = r.status_code == 200 and r.json().get("ok")
    print(f"- chat_id={chat_id} message_id={message_id}: "
          f"{'apagado' if ok else 'FALHOU'} ({r.status_code}) {r.text[:200]}")
    return ok


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python apagar_mensagens_telegram.py \"<chat_id>:<message_id>,...\"")
        return 1
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    pares = [p.strip() for p in sys.argv[1].split(",") if p.strip()]
    resultados = []
    for par in pares:
        chat_id, _, message_id = par.partition(":")
        if not (chat_id and message_id):
            print(f"[!] par invalido, esperado chat_id:message_id - {par!r}")
            continue
        resultados.append(apagar(chat_id, message_id))

    print(f"\n{sum(resultados)}/{len(resultados)} apagada(s) com sucesso")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
