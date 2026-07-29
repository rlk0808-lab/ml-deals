"""
Publica o post institucional (cartao "como funciona") no Facebook e no
Instagram. Nao roda automaticamente em nenhum pipeline - e uma acao
manual, disparada quando o conteudo institucional precisar ser
(re)publicado.

Uso: python postar_apresentacao.py
"""

import sys

import image_card
import publicar_meta as pm

TEXTO = """Como funciona a Caiu de Verdade \U0001F4C9

A gente rastreia produtos do Mercado Livre todos os dias e compara o \
preço de hoje com o HISTÓRICO real dele — não com o "de/por" que a \
loja inventa na hora.

Só vira post quando o preço bate um recorde de verdade. Sem \
estardalhaço de desconto falso.

\U0001F50E Rastreamento diário, sem parar
\U0001F4AC Grupos grátis no WhatsApp e Telegram
\U0001F310 Histórico completo de cada produto no site

Grupos e site no link da bio \U0001F447"""


def main() -> int:
    print("[apresentacao] gerando cartao...", flush=True)
    card_bytes = image_card.gerar_card_apresentacao()
    print(f"[apresentacao] cartao gerado: {len(card_bytes)} bytes", flush=True)

    print("[apresentacao] publicando no Facebook...", flush=True)
    ok_fb = pm.publicar_facebook(TEXTO, imagem_bytes=card_bytes)
    print("[apresentacao] Facebook OK" if ok_fb else "[apresentacao] Facebook FALHOU",
          flush=True)

    print("[apresentacao] hospedando imagem pro Instagram...", flush=True)
    url = pm.hospedar_imagem(card_bytes, "apresentacao_institucional.png")
    ok_ig = False
    if url:
        print(f"[apresentacao] hospedado em {url}", flush=True)
        print("[apresentacao] publicando no Instagram...", flush=True)
        ok_ig = pm.publicar_instagram(TEXTO, url)
        print("[apresentacao] Instagram OK" if ok_ig else "[apresentacao] Instagram FALHOU",
              flush=True)
    else:
        print("[apresentacao] hospedagem falhou - pulando Instagram", flush=True)

    return 0 if (ok_fb and ok_ig) else 1


if __name__ == "__main__":
    sys.exit(main())
