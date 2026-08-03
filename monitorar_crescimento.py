"""
Monitoramento de crescimento - registra 1x/dia quantos membros cada
canal/grupo do Telegram tem, pra termos historico real (nao so
"impressao") de se as estrategias de divulgacao estao funcionando.

So Telegram por enquanto - WhatsApp (Comunidade/Grupos) nao tem API
gratuita pra contar membros de fora do app.

Uso: python monitorar_crescimento.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
ARQUIVO = Path("data") / "crescimento.json"


def _contagem(chat_id: str) -> int | None:
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChatMemberCount",
        params={"chat_id": chat_id}, timeout=20)
    if r.status_code != 200:
        print(f"[crescimento] falha ao contar {chat_id}: {r.status_code} {r.text[:150]}")
        return None
    return r.json().get("result")


def main() -> int:
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    hoje = datetime.now(timezone.utc).date().isoformat()

    historico = {}
    if ARQUIVO.exists():
        historico = json.loads(ARQUIVO.read_text(encoding="utf-8"))

    ok_geral = True
    for nicho, cfg in todos.items():
        chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
        if not chat:
            continue
        n = _contagem(chat)
        if n is None:
            ok_geral = False
            continue
        registro = historico.setdefault(nicho, [])
        # 1 ponto por dia - se rodar 2x no mesmo dia (reprocessamento
        # manual), sobrescreve o de hoje em vez de duplicar
        registro[:] = [p for p in registro if p["data"] != hoje]
        registro.append({"data": hoje, "membros": n})
        print(f"[crescimento] {nicho}: {n} membro(s)")

    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok_geral else 1


if __name__ == "__main__":
    sys.exit(main())
