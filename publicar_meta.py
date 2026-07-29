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

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"

PAGE_ID = os.environ.get("META_PAGE_ID", "").strip()
PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("META_IG_USER_ID", "").strip()

_ARQUIVO_CONTAGEM_FD = Path("data") / "facebook_falso_desconto_hoje.json"


def ja_postou_falso_desconto_hoje() -> bool:
    """1 Pagina so pros 4 nichos - o limite e por dia no TOTAL, nao por
    nicho (diferente do limite do Telegram, que e por canal)."""
    hoje = datetime.now(timezone.utc).date().isoformat()
    try:
        d = json.loads(_ARQUIVO_CONTAGEM_FD.read_text(encoding="utf-8"))
        return d.get("data") == hoje
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def marcar_falso_desconto_postado_hoje() -> None:
    hoje = datetime.now(timezone.utc).date().isoformat()
    _ARQUIVO_CONTAGEM_FD.parent.mkdir(parents=True, exist_ok=True)
    _ARQUIVO_CONTAGEM_FD.write_text(json.dumps({"data": hoje}), encoding="utf-8")


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


def publicar_instagram(texto: str, imagem_url: str) -> bool:
    """
    Publica no feed do Instagram via Graph API. So aceita image_url
    PUBLICA - diferente do Facebook, essa API nunca aceita upload direto
    de bytes. Por isso so serve, por enquanto, pra Camada 1 (foto de
    produto do Mercado Livre, que ja tem URL propria); conteudo gerado
    na hora (cartao de story, falso desconto) precisa de um lugar pra
    hospedar a imagem primeiro - ainda nao resolvido.
    """
    if not (IG_USER_ID and PAGE_ACCESS_TOKEN):
        print("[meta] META_IG_USER_ID/META_PAGE_ACCESS_TOKEN nao configurado - pulado")
        return False

    try:
        r1 = requests.post(f"{GRAPH_API}/{IG_USER_ID}/media",
                           data={"image_url": imagem_url, "caption": texto,
                                 "access_token": PAGE_ACCESS_TOKEN},
                           timeout=30)
        if r1.status_code != 200:
            print(f"[meta] falha ao criar midia do Instagram ({r1.status_code}): {r1.text[:300]}")
            return False
        creation_id = r1.json().get("id")

        # a midia precisa de alguns segundos pra o Instagram baixar e
        # processar a imagem antes de aceitar publicar - sem esperar, da
        # erro "Media ID is not available" (confirmado com teste real:
        # funcionou por sorte de timing em 2 de 3 tentativas, falhou na 3a)
        for _tentativa in range(10):
            rs = requests.get(f"{GRAPH_API}/{creation_id}",
                              params={"fields": "status_code",
                                     "access_token": PAGE_ACCESS_TOKEN},
                              timeout=15)
            status = rs.json().get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                print(f"[meta] Instagram nao conseguiu processar a midia: {rs.text[:300]}")
                return False
            time.sleep(2)
        else:
            print("[meta] midia do Instagram nao ficou pronta a tempo - desistindo")
            return False

        r2 = requests.post(f"{GRAPH_API}/{IG_USER_ID}/media_publish",
                           data={"creation_id": creation_id, "access_token": PAGE_ACCESS_TOKEN},
                           timeout=30)
        if r2.status_code == 200:
            print(f"[meta] publicado no Instagram - id={r2.json().get('id', '?')}")
            return True
        print(f"[meta] falha ao publicar no Instagram ({r2.status_code}): {r2.text[:300]}")
        return False
    except requests.RequestException as e:
        print(f"[meta] erro ao publicar no Instagram: {e}")
        return False


def publicar_facebook_story(imagem_bytes: bytes | None = None,
                            imagem_url: str | None = None) -> bool:
    """
    Publica uma foto nos Stories da Pagina (nao no feed) - processo de
    2 passos da Graph API: sobe a foto sem publicar (published=false),
    depois referencia o ID dela em /photo_stories.

    Aviso: Stories via API normalmente NAO aceitam legenda nem link
    clicavel, so a imagem pura - diferente do post de feed. Se isso se
    confirmar aqui, a Story funciona mais como "chamou atencao, sem
    detalhe" do que "aqui o preco e o link", vale considerar na hora
    de decidir se compensa.
    """
    if not (PAGE_ID and PAGE_ACCESS_TOKEN):
        print("[meta] META_PAGE_ID/META_PAGE_ACCESS_TOKEN nao configurado - story pulada")
        return False
    if not imagem_bytes and not imagem_url:
        print("[meta] nem imagem_bytes nem imagem_url foram passados")
        return False

    dados = {"published": "false", "access_token": PAGE_ACCESS_TOKEN}
    try:
        if imagem_bytes:
            r = requests.post(f"{GRAPH_API}/{PAGE_ID}/photos", data=dados,
                              files={"source": ("imagem.png", imagem_bytes, "image/png")},
                              timeout=30)
        else:
            dados["url"] = imagem_url
            r = requests.post(f"{GRAPH_API}/{PAGE_ID}/photos", data=dados, timeout=30)

        if r.status_code != 200:
            print(f"[meta] falha ao subir foto pra story ({r.status_code}): {r.text[:300]}")
            return False
        photo_id = r.json().get("id")

        r2 = requests.post(f"{GRAPH_API}/{PAGE_ID}/photo_stories",
                           data={"photo_id": photo_id, "access_token": PAGE_ACCESS_TOKEN},
                           timeout=30)
        if r2.status_code == 200:
            print(f"[meta] story publicada no Facebook - photo_id={photo_id}")
            return True
        print(f"[meta] falha ao publicar story ({r2.status_code}): {r2.text[:300]}")
        return False
    except requests.RequestException as e:
        print(f"[meta] erro ao publicar story: {e}")
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
