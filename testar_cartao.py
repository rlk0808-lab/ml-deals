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
        import image_card
        import publicar_meta
        item_c1_teste = {
            "nome": "[TESTE - pode ignorar] Produto Fictício de Verificação",
            "preco": 42.90, "mediana": 97.50, "desconto": 56.0, "recorde": True,
            "imagem": "https://http2.mlstatic.com/D_NQ_NP_864793-MLA110802823579_042026-F.jpg",
        }
        print("[teste] gerando cartao de story...", flush=True)
        story_bytes = image_card.gerar_story_oferta_real(item_c1_teste)
        print(f"[teste] cartao gerado: {len(story_bytes)} bytes", flush=True)
        print("[teste] testando story do Facebook...", flush=True)
        ok_story = publicar_meta.publicar_facebook_story(imagem_bytes=story_bytes)
        print("[teste] story do Facebook publicada!" if ok_story
              else "[teste] story do Facebook FALHOU - ver log acima", flush=True)

        print("[teste] hospedando cartao pro Instagram...", flush=True)
        url_story = publicar_meta.hospedar_imagem(story_bytes, "teste_story_instagram.png")
        if url_story:
            print(f"[teste] hospedado em {url_story}", flush=True)
            print("[teste] testando story do Instagram...", flush=True)
            ok_ig_story = publicar_meta.publicar_instagram_story(url_story)
            print("[teste] story do Instagram publicada!" if ok_ig_story
                  else "[teste] story do Instagram FALHOU - ver log acima", flush=True)
        else:
            print("[teste] hospedagem FALHOU - pulando teste da story do Instagram", flush=True)

        import publicar_threads
        print("[teste] testando post de imagem no Threads...", flush=True)
        ok_threads = publicar_threads.publicar_imagem(
            "[TESTE - pode ignorar] Post de verificação da integração com o Threads.",
            item_c1_teste["imagem"])
        print("[teste] Threads publicado!" if ok_threads
              else "[teste] Threads FALHOU - ver log acima", flush=True)

    return 0 if ok else 1


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        print("[teste] ERRO NAO TRATADO:", flush=True)
        traceback.print_exc()
        codigo = 1
    sys.exit(codigo)
