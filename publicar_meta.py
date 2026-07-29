"""
Publicacao automatica na Pagina do Facebook via Graph API.

Diferente do WhatsApp: aqui a API e oficial e sancionada pela Meta pra
publicacao automatizada em Pagina Business - nao ha risco de banimento
por automatizar, e o processo de configuracao (App de desenvolvedor +
token de Pagina) e o caminho pretendido, nao um contorno.

O Instagram (e o Threads, mesma familia de API) so aceita image_url
PUBLICA no Content Publishing, nunca upload direto de bytes. Pra foto
de produto do Mercado Livre isso e facil, ja tem URL propria. Pro
cartao gerado na hora (story, falso desconto) - sem URL propria - a
imagem e hospedada no proprio repositorio do GitHub (hospedar_imagem)
e servida via raw.githubusercontent.com. Evita depender de servico de
terceiro: ja tentamos um (imgbb) que virou pago sem aviso - o GitHub e
infraestrutura que o projeto inteiro ja usa e confia.

Uso: chamado por publish_next.py depois de postar no Telegram, ou
standalone: python publicar_meta.py <nicho>
"""

import json
import os
import subprocess
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
_ARQUIVO_CONTAGEM_FEED_C1 = Path("data") / "feed_camada1_hoje.json"
_PASTA_IMAGENS_TEMP = Path("social_img")
_REPO_RAW_BASE = "https://raw.githubusercontent.com/rlk0808-lab/ml-deals/main"


def hospedar_imagem(imagem_bytes: bytes, nome_arquivo: str) -> str | None:
    """
    Sobe uma imagem gerada na hora (story, cartao de falso desconto) pro
    proprio repositorio do GitHub e devolve a URL publica. So precisa
    disso porque a API de Content Publishing (Instagram/Threads) exige
    uma URL publica de verdade - nao aceita o arquivo em bytes direto.

    Configura a identidade do git sozinho (idempotente, barato) em vez
    de assumir que quem chamou ja fez isso - o passo de teste do
    workflow, por exemplo, nao roda o git config que o passo real roda.
    Se o push falhar (ex: outro processo empurrou primeiro), so devolve
    None - quem chama trata como "sem imagem disponivel" e segue sem
    quebrar o resto da publicacao.
    """
    _PASTA_IMAGENS_TEMP.mkdir(parents=True, exist_ok=True)
    caminho = _PASTA_IMAGENS_TEMP / nome_arquivo
    caminho.write_bytes(imagem_bytes)

    try:
        subprocess.run(["git", "config", "user.name", "publicador-bot"],
                       check=True, timeout=10, capture_output=True)
        subprocess.run(["git", "config", "user.email",
                        "publicador-bot@users.noreply.github.com"],
                       check=True, timeout=10, capture_output=True)
        subprocess.run(["git", "add", str(caminho)], check=True, timeout=15,
                       capture_output=True)
        commit = subprocess.run(["git", "commit", "-m", f"social: {nome_arquivo}"],
                                capture_output=True, timeout=15)
        saida_commit = commit.stdout + commit.stderr
        if commit.returncode != 0 and b"nothing to commit" not in saida_commit:
            print(f"[meta] git commit da imagem falhou: {saida_commit.decode(errors='replace')[:300]}")
            return None
        subprocess.run(["git", "push", "origin", "main"], check=True, timeout=30,
                       capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        detalhe = getattr(e, "stderr", b"") or b""
        print(f"[meta] falha ao hospedar imagem no GitHub: {e} "
              f"{detalhe.decode(errors='replace')[:300]}")
        return None

    print(f"[meta] imagem hospedada: {caminho}")
    return f"{_REPO_RAW_BASE}/{caminho.as_posix()}"


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


def ja_postou_feed_camada1_hoje() -> bool:
    """Mesma logica do gate de falso desconto: 1 Pagina so pros 4 nichos,
    o feed (nao a story) fica pausado em 1 post/dia no TOTAL pra manter
    uma cara de catalogo, nao de spam."""
    hoje = datetime.now(timezone.utc).date().isoformat()
    try:
        d = json.loads(_ARQUIVO_CONTAGEM_FEED_C1.read_text(encoding="utf-8"))
        return d.get("data") == hoje
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def marcar_feed_camada1_postado_hoje() -> None:
    hoje = datetime.now(timezone.utc).date().isoformat()
    _ARQUIVO_CONTAGEM_FEED_C1.parent.mkdir(parents=True, exist_ok=True)
    _ARQUIVO_CONTAGEM_FEED_C1.write_text(json.dumps({"data": hoje}), encoding="utf-8")


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


def _publicar_midia_instagram(dados_media: dict, rotulo: str) -> bool:
    """
    Passos comuns do Content Publishing API do Instagram (feed OU story,
    so muda o payload que chega aqui): cria o container de midia, espera
    processar, publica. So aceita image_url PUBLICA - diferente do
    Facebook, essa API nunca aceita upload direto de bytes.
    """
    if not (IG_USER_ID and PAGE_ACCESS_TOKEN):
        print(f"[meta] META_IG_USER_ID/META_PAGE_ACCESS_TOKEN nao configurado - {rotulo} pulado")
        return False

    try:
        dados_media["access_token"] = PAGE_ACCESS_TOKEN
        r1 = requests.post(f"{GRAPH_API}/{IG_USER_ID}/media", data=dados_media, timeout=30)
        if r1.status_code != 200:
            print(f"[meta] falha ao criar midia ({rotulo}) ({r1.status_code}): {r1.text[:300]}")
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
                print(f"[meta] Instagram nao conseguiu processar a midia ({rotulo}): {rs.text[:300]}")
                return False
            time.sleep(2)
        else:
            print(f"[meta] midia ({rotulo}) nao ficou pronta a tempo - desistindo")
            return False

        r2 = requests.post(f"{GRAPH_API}/{IG_USER_ID}/media_publish",
                           data={"creation_id": creation_id, "access_token": PAGE_ACCESS_TOKEN},
                           timeout=30)
        if r2.status_code == 200:
            print(f"[meta] {rotulo} publicado(a) no Instagram - id={r2.json().get('id', '?')}")
            return True
        print(f"[meta] falha ao publicar {rotulo} no Instagram ({r2.status_code}): {r2.text[:300]}")
        return False
    except requests.RequestException as e:
        print(f"[meta] erro ao publicar {rotulo} no Instagram: {e}")
        return False


def publicar_instagram(texto: str, imagem_url: str) -> bool:
    """Publica no FEED do Instagram - foto de produto do Mercado Livre
    (Camada 1) ou uma imagem gerada e hospedada via hospedar_imagem()
    (falso desconto)."""
    return _publicar_midia_instagram(
        {"image_url": imagem_url, "caption": texto}, "feed")


def publicar_instagram_story(imagem_url: str) -> bool:
    """Publica nos STORIES do Instagram - sem legenda (mesma limitacao
    do Facebook), por isso so faz sentido com uma imagem que ja tem o
    texto queimado nela (gerar_story_oferta_real)."""
    return _publicar_midia_instagram(
        {"image_url": imagem_url, "media_type": "STORIES"}, "story")


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
