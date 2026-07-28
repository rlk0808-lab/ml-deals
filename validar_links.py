"""
Valida os links de afiliado cadastrados em data/links_afiliado.json.

Segue o redirect de cada link "meli.la/..." e confere se ainda aponta pra
um produto real do Mercado Livre. Roda 1x/dia (cron-job.org, ver
.github/workflows/validar_links.yml).

So marca "quebrado" quando da pra confirmar de verdade (404/410, redirect
caiu fora do dominio do ML, ou caiu na home sem produto nenhum) - os
jeitos como um link de afiliado expirado costuma se manifestar. Qualquer
outra coisa (timeout, bloqueio antibot, 5xx, link que nunca saiu do
proprio meli.la) vira "inconclusivo" e CONTINUA em uso - ausencia de
prova nao e prova de defeito (ver o docstring de links_afiliado.py).

Uso: python validar_links.py
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import links_afiliado

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ADMIN = os.environ.get("TELEGRAM_CHAT_ADMIN", "").strip()

TIMEOUT = 20
WORKERS = 8
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ml-deals-validador/1.0)"}

DOMINIOS_VALIDOS = ("mercadolivre.com.br", "mercadolibre.com")

# depois de tantas checagens inconclusivas SEGUIDAS, avisa o Robson pra
# olhar na mao - mas nao marca como quebrado, so sinaliza que a checagem
# automatica esta cega pra esse link (bloqueio antibot persistente, etc)
LIMITE_INCONCLUSIVOS_PARA_AVISO = 5

sess = requests.Session()


# ----------------------------------------------------------------------
# CHECAGEM
# ----------------------------------------------------------------------

def checar(link: str) -> str:
    """Segue o redirect e devolve 'ok', 'quebrado' ou 'inconclusivo'."""
    r = None
    for tentativa in range(3):
        try:
            r = sess.get(link, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True)
        except requests.RequestException:
            return "inconclusivo"

        if r.status_code == 429:
            time.sleep(2 * (tentativa + 1))
            continue
        break

    if r.status_code in (404, 410):
        return "quebrado"
    if r.status_code != 200:
        return "inconclusivo"

    final = urlparse(r.url)

    # o link nunca saiu do proprio meli.la (sem redirect) - pode ser
    # pagina de erro do encurtador OU um redirect via JS que o requests
    # nao segue. Sem confirmacao de nenhum dos dois lados, fica em duvida.
    if "meli.la" in final.netloc:
        return "inconclusivo"

    if not any(final.netloc.endswith(d) for d in DOMINIOS_VALIDOS):
        return "quebrado"

    # redirect caiu na home do ML (sem path nenhum) = sinal classico de
    # link de afiliado expirado, o ML manda pra home em vez de dar 404
    if final.path in ("", "/"):
        return "quebrado"

    return "ok"


# ----------------------------------------------------------------------
# AVISO
# ----------------------------------------------------------------------

def avisar(quebrados: list[tuple[str, dict]],
           avisos_inconclusivo: list[tuple[str, dict]]) -> None:
    if not (quebrados or avisos_inconclusivo):
        return
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ADMIN):
        print("[validar] TELEGRAM_CHAT_ADMIN nao configurado - aviso so no log")
        return

    linhas = []
    if quebrados:
        linhas.append(f"⚠️ {len(quebrados)} link(s) de afiliado QUEBRADO(S):")
        linhas.append("")
        for pid, e in quebrados:
            linhas.append(f"{pid} - {e.get('nome') or '(sem nome)'}\n{e['link']}")

    if avisos_inconclusivo:
        if linhas:
            linhas.append("")
        linhas.append(f"🔎 {len(avisos_inconclusivo)} link(s) inconclusivo(s) ha "
                       f"{LIMITE_INCONCLUSIVOS_PARA_AVISO}+ checagens seguidas "
                       f"(continuam em uso, mas vale olhar na mao):")
        linhas.append("")
        for pid, e in avisos_inconclusivo:
            linhas.append(f"{pid} - {e.get('nome') or '(sem nome)'}\n{e['link']}")

    texto = "\n".join(linhas)
    try:
        r = sess.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ADMIN, "text": texto[:4000],
                  "disable_web_page_preview": True},
            timeout=20)
        print(f"[validar] aviso enviado: {r.status_code}")
    except requests.RequestException as e:
        print(f"[validar] falha ao enviar aviso: {e}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main() -> int:
    tabela = links_afiliado.carregar()
    agora = datetime.now(timezone.utc).isoformat()

    # "sem_programa" nao tem link pra checar; "quebrado" so volta a "ok"
    # quando o Robson recadastra manualmente (importar_novos ja reseta
    # o status pra "ok" nesse caso) - re-checar nao teria efeito nenhum
    a_checar = [(pid, e) for pid, e in tabela.items()
                if e.get("link") and e.get("status") not in
                ("sem_programa", "quebrado")]

    print(f"[validar] {len(a_checar)} link(s) pra checar")
    if not a_checar:
        print("OK")
        return 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        resultados = list(ex.map(lambda item: checar(item[1]["link"]), a_checar))

    quebrados, avisos_inconclusivo = [], []
    contagem = {"ok": 0, "quebrado": 0, "inconclusivo": 0}

    for (pid, e), resultado in zip(a_checar, resultados):
        contagem[resultado] += 1
        e["ultima_checagem"] = agora

        if resultado == "ok":
            e["status"] = "ok"
            e["inconclusivos_seguidos"] = 0
        elif resultado == "quebrado":
            e["status"] = "quebrado"
            e["inconclusivos_seguidos"] = 0
            quebrados.append((pid, e))
            print(f"[validar] QUEBRADO {pid} - {e.get('nome', '')[:50]}")
        else:
            e["status"] = "inconclusivo"
            e["inconclusivos_seguidos"] = e.get("inconclusivos_seguidos", 0) + 1
            if e["inconclusivos_seguidos"] == LIMITE_INCONCLUSIVOS_PARA_AVISO:
                avisos_inconclusivo.append((pid, e))

    links_afiliado.salvar(tabela)
    print(f"[validar] ok={contagem['ok']} quebrado={contagem['quebrado']} "
          f"inconclusivo={contagem['inconclusivo']}")

    avisar(quebrados, avisos_inconclusivo)

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
