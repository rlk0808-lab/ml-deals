"""
Publicador - tira 1 item da fila e posta no Telegram.
Roda a cada 30 min (07h-23h30 BRT), separado do coletor (que roda 4x/dia).

Separar coleta de publicacao existe por um motivo: decidir o que e uma
oferta real e caro (consulta API, calcula historico) e so precisa
acontecer 4x/dia. Publicar e barato e pode ser espacado, pra o canal
nao parecer bot cuspindo 5 mensagens de uma vez.

Uso: python publish_next.py <nicho>
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

# item de Camada 2 ("melhor preco HOJE") perde validade depois disso.
# NAO e o mecanismo principal de frescor - o coletor ja atualiza o preco
# de quem esta na fila a cada rodada (~4-5h, via refrescar_camada2_na_fila).
# Isso aqui e so a rede de seguranca pro caso raro do produto sumir da
# coleta (ex: ficou sem estoque) e nunca mais ser atualizado.
VALIDADE_CAMADA2_HORAS = 10
# Camada 1 e mais estavel (selo de historico, nao muda a cada hora), mas
# tambem tem teto de seguranca pra fila nao acumular lixo antigo.
VALIDADE_CAMADA1_HORAS = 30
# Falso desconto: o "de/por" da loja costuma ficar fixo por dias, entao
# nao e tao sensivel a hora quanto a Camada 2 - mas ainda assim tem teto.
VALIDADE_FALSO_DESCONTO_HORAS = 24


def link(url: str, affiliate_tag: str) -> str:
    if affiliate_tag and url:
        return f"{url}{'&' if '?' in url else '?'}{affiliate_tag}"
    return url


def montar_camada1(o: dict, cfg: dict, affiliate_tag: str) -> str:
    selo = "MENOR PRECO JA REGISTRADO" if o["recorde"] else "QUEDA REAL DE PRECO"
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} {selo}\n\n"
            f"{o['nome']}\n\n"
            f"Por R$ {o['preco']:.2f}\n"
            f"Preco habitual: R$ {o['mediana']:.2f}\n"
            f"{o['desconto']:.0f}% abaixo do normal"
            f"{entrega}\n\n"
            f"{link(o['permalink'], affiliate_tag)}")


def montar_camada2(o: dict, cfg: dict, affiliate_tag: str) -> str:
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} MELHOR PRECO ENTRE OS VENDEDORES HOJE\n\n"
            f"{o['nome']}\n\n"
            f"R$ {o['preco']:.2f}\n"
            f"(comparado entre {o['n_ofertas']} vendedores)"
            f"{entrega}\n\n"
            f"{link(o['permalink'], affiliate_tag)}")


def montar_falso_desconto(o: dict, cfg: dict, affiliate_tag: str) -> str:
    """
    Tom factual, nunca acusatorio - mostra o que a loja anuncia e o que o
    NOSSO historico real mostra, e deixa os numeros falarem. Nao xinga o
    vendedor nem usa hiperbole; a comparacao lado a lado ja e o argumento.
    """
    if o["desconto_real"] >= 0:
        comparacao = (f"hoje está {o['desconto_real']:.1f}% abaixo do normal "
                      f"(não os {o['desconto_anunciado']:.0f}% anunciados)")
    else:
        comparacao = f"hoje está {abs(o['desconto_real']):.1f}% ACIMA do preço normal"
    return (f"🔍 {cfg['emoji']} DE OLHO NO \"DESCONTO\"\n\n"
            f"{o['nome']}\n\n"
            f"A loja anuncia: de R$ {o['preco_original']:.2f} por R$ {o['preco']:.2f} "
            f"(-{o['desconto_anunciado']:.0f}%)\n\n"
            f"Nosso histórico real ({o['dias_historico']} dias de coleta): "
            f"preço normal é R$ {o['mediana']:.2f} — {comparacao}.\n\n"
            f"{link(o['permalink'], affiliate_tag)}")


def montar_mensagem(item: dict, cfg: dict, affiliate_tag: str) -> str:
    if item.get("tipo") == "camada2":
        return montar_camada2(item, cfg, affiliate_tag)
    if item.get("tipo") == "falso_desconto":
        return montar_falso_desconto(item, cfg, affiliate_tag)
    return montar_camada1(item, cfg, affiliate_tag)


def esta_vencido(item: dict) -> bool:
    try:
        enfileirado = datetime.fromisoformat(item["enfileirado_em"])
    except (KeyError, ValueError):
        return True  # sem timestamp -> nao confiamos, descarta

    limites = {
        "camada2": VALIDADE_CAMADA2_HORAS,
        "falso_desconto": VALIDADE_FALSO_DESCONTO_HORAS,
    }
    limite = limites.get(item.get("tipo"), VALIDADE_CAMADA1_HORAS)
    idade = datetime.now(timezone.utc) - enfileirado
    return idade > timedelta(hours=limite)


def enviar(item: dict, cfg: dict, chat: str, affiliate_tag: str) -> bool:
    texto = montar_mensagem(item, cfg, affiliate_tag)
    imagem = item.get("imagem")
    print(f"[telegram] preparando envio - tipo={item.get('tipo')} "
          f"nome={item['nome'][:40]!r}", flush=True)

    try:
        if item.get("tipo") == "falso_desconto":
            # cartao gerado na hora (Pillow) - se falhar por qualquer
            # motivo, cai pra mensagem de texto puro, nunca perde o post
            try:
                import image_card
                png_bytes = image_card.gerar_cartao_falso_desconto(item, cfg)
                print(f"[cartao] imagem gerada: {len(png_bytes)} bytes", flush=True)
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    data={"chat_id": chat, "caption": texto[:1024]},
                    files={"photo": ("cartao.png", png_bytes, "image/png")},
                    timeout=30)
                if r.status_code != 200:
                    print(f"[telegram] cartao falhou ({r.status_code}): {r.text[:300]}")
                    print("[telegram] tentando sem imagem...")
                    r = requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": chat, "text": texto}, timeout=20)
            except Exception:
                print("[cartao] erro ao gerar/enviar imagem - caindo pra texto:", flush=True)
                traceback.print_exc()
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat, "text": texto}, timeout=20)
        elif imagem:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                json={"chat_id": chat, "photo": imagem, "caption": texto[:1024]},
                timeout=20)
            if r.status_code != 200:
                print(f"[telegram] sendPhoto falhou ({r.status_code}): {r.text[:300]}")
                print("[telegram] tentando sem imagem...")
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat, "text": texto}, timeout=20)
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat, "text": texto}, timeout=20)
        print(f"[telegram] {r.status_code} - {item['nome'][:45]}", flush=True)
        if r.status_code != 200:
            print(f"[telegram] corpo da resposta: {r.text[:300]}", flush=True)
        return r.status_code == 200
    except Exception:
        print("[telegram] erro nao tratado ao enviar:", flush=True)
        traceback.print_exc()
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python publish_next.py <nicho>")
        return 1
    nicho = sys.argv[1]

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    if nicho not in todos:
        print(f"[!] nicho '{nicho}' nao existe")
        return 1
    cfg = todos[nicho]

    chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
    affiliate_tag = os.environ.get("ML_AFFILIATE_TAG", "").strip()
    if not (TELEGRAM_TOKEN and chat):
        print(f"[!] {cfg['telegram_chat_env']} ou TELEGRAM_TOKEN nao configurado")
        return 1

    f_fila = Path("data") / nicho / "fila_publicacao.json"
    f_estado_c2 = Path("data") / nicho / "camada2_state.json"

    if not f_fila.exists():
        print("[fila] arquivo nao existe ainda - nada a publicar")
        return 0

    fila = json.loads(f_fila.read_text(encoding="utf-8"))

    # limpa vencidos primeiro (nao posta preco velho como se fosse de hoje)
    antes = len(fila)
    fila = [it for it in fila if not esta_vencido(it)]
    vencidos = antes - len(fila)
    if vencidos:
        print(f"[fila] {vencidos} item(ns) vencido(s) descartado(s)")

    if not fila:
        print("[fila] vazia - nada a publicar nesta rodada")
        f_fila.write_text(json.dumps(fila, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return 0

    item = fila.pop(0)  # FIFO - o mais antigo primeiro
    ok = enviar(item, cfg, chat, affiliate_tag)

    if ok and item.get("tipo") == "camada2":
        estado = json.loads(f_estado_c2.read_text(encoding="utf-8")) \
                 if f_estado_c2.exists() else {}
        estado[item["product_id"]] = {
            "preco": item["preco"], "seller_id": item["seller_id"]}
        f_estado_c2.write_text(json.dumps(estado, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    if not ok:
        # falhou o envio - devolve pro fim da fila pra tentar de novo depois
        fila.append(item)
        print("[fila] envio falhou, item devolvido ao fim da fila")

    f_fila.write_text(json.dumps(fila, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[fila] restam {len(fila)} item(ns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
