"""
Publicacao automatica na Pagina do Facebook via Graph API.

Diferente do WhatsApp: aqui a API e oficial e sancionada pela Meta pra
publicacao automatizada em Pagina Business - nao ha risco de banimento
por automatizar, e o processo de configuracao (App de desenvolvedor +
token de Pagina) e o caminho pretendido, nao um contorno.

O Instagram entra depois - a API dele (Content Publishing) so aceita
image_url publica, nunca upload direto de bytes. Pra fotos de produto
(camada1/camada2) isso e facil, ja temos a URL do Mercado Livre. Pro
cartao gerado de falso desconto (sem URL propria) vai precisar hospedar
a imagem em algum lugar publico primeiro (provavel: docs/ do proprio
site) antes de conseguir postar no Instagram - ainda nao resolvido.

Uso: chamado por publish_next.py depois de postar no Telegram, ou
standalone: python publicar_meta.py <nicho>
"""

import os
import sys

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"

PAGE_ID = os.environ.get("META_PAGE_ID", "").strip()
PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "").strip()


def publicar_facebook(texto: str, imagem_bytes: bytes | None = None,
                      imagem_url: str | None = None) -> bool:
    """
    Publica uma foto na Pagina do Facebook. Manda OU bytes (upload
    direto - usado pro cartao gerado de falso desconto) OU uma URL
    publica (usado pra foto de produto do Mercado Livre, que ja tem
    URL propria). Exatamente um dos dois precisa vir preenchido.
    """
    if not (PAGE_ID and PAGE_ACCESS_TOKEN):
        print("[meta] META_PAGE_ID/META_PAGE_ACCESS_TOKEN nao configurado - pulado")
        return False
    if not imagem_bytes and not imagem_url:
        print("[meta] nem imagem_bytes nem imagem_url foram passados")
        return False

    url = f"{GRAPH_API}/{PAGE_ID}/photos"
    dados = {"caption": texto, "access_token": PAGE_ACCESS_TOKEN}

    try:
        if imagem_bytes:
            r = requests.post(url, data=dados,
                              files={"source": ("imagem.png", imagem_bytes, "image/png")},
                              timeout=30)
        else:
            dados["url"] = imagem_url
            r = requests.post(url, data=dados, timeout=30)

        if r.status_code == 200:
            print(f"[meta] publicado no Facebook - post_id={r.json().get('post_id', '?')}")
            return True
        print(f"[meta] falha ao publicar no Facebook ({r.status_code}): {r.text[:300]}")
        return False
    except requests.RequestException as e:
        print(f"[meta] erro ao publicar no Facebook: {e}")
        return False


def main() -> int:
    """Teste manual: publica 1 mensagem de teste na Pagina, sem tocar na fila real."""
    if len(sys.argv) < 2:
        print("uso: python publicar_meta.py <nicho>")
        return 1

    texto = ("[TESTE - pode ignorar] Validando publicação automática no Facebook. "
             "caiudeverdade.github.io")
    ok = publicar_facebook(texto, imagem_url="https://http2.mlstatic.com/D_NQ_NP_864793-MLA110802823579_042026-F.jpg")
    print("publicado com sucesso!" if ok else "FALHOU - ver log acima")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
