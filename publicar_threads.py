"""
Integracao com a API do Threads - grafo PROPRIO (graph.threads.net),
separado do Facebook/Instagram apesar de ser tudo Meta. Mesmo fluxo de
2 passos do Instagram: cria o container de midia, espera processar,
so entao publica.

Diferente do feed do Facebook/Instagram (travado em 1x/dia pra manter
cara de catalogo), o Threads e pensado pra volume alto - vai junto com
o Telegram, sem gate. So imagens com URL publica sao aceitas (igual
Instagram, nunca upload direto de bytes).
"""

import os
import time

import requests

GRAPH_API = "https://graph.threads.net/v1.0"
THREADS_USER_ID = os.environ.get("THREADS_USER_ID", "").strip()
THREADS_ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()

LIMITE_TEXTO = 500


def _truncar(texto: str) -> str:
    if len(texto) <= LIMITE_TEXTO:
        return texto
    return texto[:LIMITE_TEXTO - 1] + "…"


def _criar_e_publicar(dados_media: dict, rotulo: str) -> bool:
    dados_media = {**dados_media, "access_token": THREADS_ACCESS_TOKEN}
    r = requests.post(f"{GRAPH_API}/{THREADS_USER_ID}/threads", data=dados_media, timeout=30)
    if r.status_code != 200:
        print(f"[threads] falha ao criar container ({rotulo}): "
              f"{r.status_code} {r.text[:300]}", flush=True)
        return False
    creation_id = r.json().get("id")
    if not creation_id:
        print(f"[threads] resposta sem id ({rotulo}): {r.text[:300]}", flush=True)
        return False

    for _ in range(10):
        time.sleep(2)
        status_r = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status", "access_token": THREADS_ACCESS_TOKEN},
            timeout=20)
        status = status_r.json().get("status")
        if status == "FINISHED":
            break
        if status == "ERROR":
            print(f"[threads] container deu erro ({rotulo}): {status_r.text[:300]}", flush=True)
            return False
    else:
        print(f"[threads] container nao terminou de processar a tempo ({rotulo})", flush=True)
        return False

    pub_r = requests.post(
        f"{GRAPH_API}/{THREADS_USER_ID}/threads_publish",
        data={"creation_id": creation_id, "access_token": THREADS_ACCESS_TOKEN},
        timeout=30)
    ok = pub_r.status_code == 200
    print(f"[threads] {rotulo}: {'publicado' if ok else 'FALHOU'} "
          f"({pub_r.status_code}) {pub_r.text[:300]}", flush=True)
    return ok


def publicar_texto(texto: str) -> bool:
    if not (THREADS_USER_ID and THREADS_ACCESS_TOKEN):
        print("[threads] THREADS_USER_ID/THREADS_ACCESS_TOKEN nao configurados - pulando",
              flush=True)
        return False
    return _criar_e_publicar({"media_type": "TEXT", "text": _truncar(texto)}, "texto")


def publicar_imagem(texto: str, imagem_url: str) -> bool:
    if not (THREADS_USER_ID and THREADS_ACCESS_TOKEN):
        print("[threads] THREADS_USER_ID/THREADS_ACCESS_TOKEN nao configurados - pulando",
              flush=True)
        return False
    return _criar_e_publicar(
        {"media_type": "IMAGE", "image_url": imagem_url, "text": _truncar(texto)}, "imagem")
