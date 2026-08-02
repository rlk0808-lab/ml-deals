"""
Disparo manual (workflow_dispatch) - gera 1 video de PROTOTIPO a partir da
melhor oferta real disponivel hoje (qualquer nicho) e manda pro Telegram
pessoal do Robson, pra ele avaliar o resultado sem precisar mexer em
codigo. Nao entra na esteira de publicacao automatica - so validacao.

Uso: python enviar_prototipo_video.py
"""

import json
import os
from pathlib import Path

import requests

import site_builder
import video_card

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ROBSON = os.environ.get("TELEGRAM_CHAT_ROBSON", "").strip()

RAIZ_URL = os.environ.get("SITE_URL", "").strip().rstrip("/") or "."


def main() -> int:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ROBSON):
        print("[!] TELEGRAM_TOKEN/TELEGRAM_CHAT_ROBSON nao configurados", flush=True)
        return 1

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    melhor = None
    melhor_cfg = None
    for nicho, cfg in todos.items():
        arq = Path("data") / nicho / "ofertas.json"
        if not arq.exists():
            continue
        arq_watchlist = Path("data") / nicho / "watchlist.json"
        watchlist = (json.loads(arq_watchlist.read_text(encoding="utf-8"))
                     if arq_watchlist.exists() else {})
        for o in json.loads(arq.read_text(encoding="utf-8")):
            if not o.get("imagem"):
                o["imagem"] = watchlist.get(o["product_id"], {}).get("imagem")
            if not o.get("imagem"):
                continue
            if melhor is None or o.get("desconto", 0) > melhor.get("desconto", 0):
                melhor, melhor_cfg = o, cfg

    if not melhor:
        print("[video-prototipo] nenhuma oferta com imagem disponivel hoje", flush=True)
        return 0

    print(f"[video-prototipo] escolhido: {melhor['nome'][:50]!r} "
          f"(-{melhor['desconto']:.0f}%)", flush=True)

    video_bytes = video_card.gerar_video_oferta_real(melhor)
    legenda = video_card.gerar_descricao_video(
        melhor, melhor_cfg, RAIZ_URL,
        site_builder.WHATSAPP_LINK, site_builder.TELEGRAM_LINK)

    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
        data={"chat_id": TELEGRAM_CHAT_ROBSON,
              "caption": "\U0001F3AC PROTÓTIPO de vídeo curto - avalie e me diga o que ajustar:\n\n"
                        + legenda[:900]},
        files={"video": ("prototipo.mp4", video_bytes, "video/mp4")},
        timeout=60)
    print(f"[video-prototipo] envio: {r.status_code} {r.text[:200]}", flush=True)
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
