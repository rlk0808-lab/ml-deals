"""
Envia um cartao de "falso desconto" de TESTE pro Telegram de verdade -
dados sinteticos, claramente marcados, so pra confirmar visualmente que
a geracao da imagem funciona no ambiente real do GitHub Actions (com as
fontes do runner, o Pillow instalado, etc). Nao mexe na fila real nem
conta pro limite diario de 3 posts.

Uso: python testar_cartao.py <nicho>
"""

import json
import os
import sys
import traceback
from pathlib import Path

print("[teste] script iniciado", flush=True)

import publish_next as pub

print("[teste] modulos importados com sucesso", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python testar_cartao.py <nicho>", flush=True)
        return 1
    nicho = sys.argv[1]
    print(f"[teste] nicho recebido: {nicho}", flush=True)

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    if nicho not in todos:
        print(f"[!] nicho '{nicho}' nao existe", flush=True)
        return 1
    cfg = todos[nicho]

    chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
    print(f"[teste] token presente: {bool(pub.TELEGRAM_TOKEN)} | "
          f"chat presente: {bool(chat)}", flush=True)
    if not (pub.TELEGRAM_TOKEN and chat):
        print(f"[!] {cfg['telegram_chat_env']} ou TELEGRAM_TOKEN nao configurado", flush=True)
        return 1

    item_teste = {
        "tipo": "falso_desconto",
        "nome": "[TESTE - pode ignorar] Produto Fictício de Verificação",
        "preco": 99.90,
        "preco_original": 189.90,
        "desconto_anunciado": 47.4,
        "desconto_real": 0.1,
        "mediana": 100.0,
        "dias_historico": 10,
        "permalink": "https://www.mercadolivre.com.br/",
        "seller_id": "teste",
        "imagem": None,
    }

    print(f"[teste] enviando cartao de teste pra {cfg['telegram_chat_env']}...", flush=True)
    ok = pub.enviar(item_teste, cfg, chat)
    print("[teste] enviado com sucesso!" if ok else "[teste] FALHOU - ver log acima", flush=True)

    # so testa a story 1x (nao 1x por nicho - e a mesma Pagina do Facebook
    # pros 4 nichos, rodar em todos postaria 4 stories de teste iguais)
    if nicho == "livros":
        import publicar_meta
        print("[teste] testando story do Facebook...", flush=True)
        ok_story = publicar_meta.publicar_facebook_story(
            imagem_url="https://http2.mlstatic.com/D_NQ_NP_864793-MLA110802823579_042026-F.jpg")
        print("[teste] story publicada!" if ok_story else "[teste] story FALHOU - ver log acima",
              flush=True)

    return 0 if ok else 1


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        print("[teste] ERRO NAO TRATADO:", flush=True)
        traceback.print_exc()
        codigo = 1
    sys.exit(codigo)
