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

import links_afiliado
import publicar_meta
import publicar_threads

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

# item de Camada 2 ("melhor preco HOJE") perde validade depois disso.
# NAO e o mecanismo principal de frescor - o coletor ja atualiza o preco
# de quem esta na fila a cada rodada (~4-5h, via refrescar_camada2_na_fila).
# Isso aqui e so a rede de seguranca pro caso raro do produto sumir da
# coleta (ex: ficou sem estoque) e nunca mais ser atualizado.
VALIDADE_CAMADA2_HORAS = 10

SITE_URL = "https://rlk0808-lab.github.io/ml-deals"

# So pro Facebook/Instagram - o Telegram ja tem os proprios grupos
# fixados no topo do canal, um convite pro WhatsApp/Telegram DENTRO do
# proprio Telegram fica sem sentido (mesma razao pela qual removemos
# isso do texto do Telegram antes). Facebook/Instagram sao o publico
# que ainda nao esta em nenhum grupo, faz sentido puxar pra la.
WHATSAPP_LINK = "https://chat.whatsapp.com/JGvCrkWCfBmKS9KW4m1HD2"
TELEGRAM_LINK = "https://t.me/addlist/2TD1Un1OO5Y3MGI5"


def _texto_para_feed_social(texto: str) -> str:
    return (f"{texto}\n\n"
            f"💬 WhatsApp: {WHATSAPP_LINK}\n"
            f"📢 Telegram: {TELEGRAM_LINK}")


def link_site(o: dict, cfg: dict) -> str:
    """Link direto pra pagina desse produto no site - mostra o grafico
    completo do historico, reforca credibilidade antes da pessoa clicar
    pra comprar, e funciona como porta de entrada pra busca no site."""
    pid = o.get("product_id", "")
    return f"{SITE_URL}/{cfg['slug']}/{pid}.html"
# Camada 1 e mais estavel (selo de historico, nao muda a cada hora), mas
# tambem tem teto de seguranca pra fila nao acumular lixo antigo.
VALIDADE_CAMADA1_HORAS = 30
# Falso desconto: o "de/por" da loja costuma ficar fixo por dias, entao
# nao e tao sensivel a hora quanto a Camada 2 - mas ainda assim tem teto.
VALIDADE_FALSO_DESCONTO_HORAS = 24
# Cupom entra na FRENTE da fila (e urgente) - se em 6h ainda nao saiu,
# algo travou e o cupom provavelmente ja nao vale mais a pena repassar.
VALIDADE_CUPOM_HORAS = 6


def link(o: dict) -> str:
    """
    Link do produto para o post.

    Usa o link rastreado da tabela (gerado na mao) quando existe - e o
    unico formato que o ML contabiliza. Sem link cadastrado, cai no link
    normal do produto: o post sai igual, so nao rastreia.
    """
    return links_afiliado.resolver(o.get("product_id", ""),
                                   o.get("permalink", ""))


def montar_camada1(o: dict, cfg: dict) -> str:
    selo = "MENOR PRECO JA REGISTRADO" if o["recorde"] else "QUEDA REAL DE PRECO"
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} {selo}\n\n"
            f"{o['nome']}\n\n"
            f"Por R$ {o['preco']:.2f}\n"
            f"Preco habitual: R$ {o['mediana']:.2f}\n"
            f"{o['desconto']:.0f}% abaixo do normal"
            f"{entrega}\n\n"
            f"{link(o)}\n\n"
            f"📊 Veja o histórico completo: {link_site(o, cfg)}")


def montar_camada2(o: dict, cfg: dict) -> str:
    entrega = "\nEntrega Full" if o.get("full") else (
        "\nFrete gratis" if o.get("frete_gratis") else "")
    return (f"{cfg['emoji']} MELHOR PRECO ENTRE OS VENDEDORES HOJE\n\n"
            f"{o['nome']}\n\n"
            f"R$ {o['preco']:.2f}\n"
            f"(comparado entre {o['n_ofertas']} vendedores)"
            f"{entrega}\n\n"
            f"{link(o)}\n\n"
            f"📊 Veja o histórico completo: {link_site(o, cfg)}")


def montar_falso_desconto(o: dict, cfg: dict) -> str:
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
            f"{link(o)}\n\n"
            f"📊 Veja o histórico completo: {link_site(o, cfg)}")


def montar_cupom(o: dict, cfg: dict) -> str:
    import cupons
    return cupons.montar_cupom(o.get("codigo", ""), o.get("texto_cupom", ""), cfg)


def _footer_cupom_ativo(cfg: dict) -> str:
    """Cupom colado ha menos de 24h pro nicho (ver cupons.py) - anexado
    nas mensagens normais, alem do post dedicado que ja sai na hora."""
    import cupons
    ativo = cupons.obter_cupom_ativo(cfg["slug"])
    if not ativo:
        return ""
    return f"\n\n🎟️ Cupom ativo hoje: {ativo['codigo']} - {ativo['texto']}"


def montar_mensagem(item: dict, cfg: dict) -> str:
    if item.get("tipo") == "cupom":
        return montar_cupom(item, cfg)
    if item.get("tipo") == "camada2":
        texto = montar_camada2(item, cfg)
    elif item.get("tipo") == "falso_desconto":
        texto = montar_falso_desconto(item, cfg)
    else:
        texto = montar_camada1(item, cfg)
    return texto + _footer_cupom_ativo(cfg)


def esta_vencido(item: dict) -> bool:
    try:
        enfileirado = datetime.fromisoformat(item["enfileirado_em"])
    except (KeyError, ValueError):
        return True  # sem timestamp -> nao confiamos, descarta

    limites = {
        "camada2": VALIDADE_CAMADA2_HORAS,
        "falso_desconto": VALIDADE_FALSO_DESCONTO_HORAS,
        "cupom": VALIDADE_CUPOM_HORAS,
    }
    limite = limites.get(item.get("tipo"), VALIDADE_CAMADA1_HORAS)
    idade = datetime.now(timezone.utc) - enfileirado
    return idade > timedelta(hours=limite)


def enviar(item: dict, cfg: dict, chat: str) -> bool:
    # SEM convite pro WhatsApp aqui de proposito: o Robson copia o texto
    # renderizado direto do Telegram pra colar no WhatsApp (fluxo manual
    # de repost), entao qualquer coisa "so pro Telegram" escrita na
    # mensagem vaza pro WhatsApp junto - inclusive um convite pro proprio
    # WhatsApp, o que fica sem sentido dentro de um grupo que ja e do
    # WhatsApp. O convite pro WhatsApp mora na mensagem fixada de cada
    # canal (configurada direto no Telegram, fora deste codigo).
    texto = montar_mensagem(item, cfg)
    imagem = item.get("imagem")
    print(f"[telegram] preparando envio - tipo={item.get('tipo')} "
          f"nome={item['nome'][:40]!r}", flush=True)

    try:
        if item.get("tipo") == "falso_desconto":
            # cartao gerado na hora (Pillow) - se falhar por qualquer
            # motivo, cai pra mensagem de texto puro, nunca perde o post
            try:
                import image_card
                png_bytes = image_card.gerar_cartao_falso_desconto(item)
                print(f"[cartao] imagem gerada: {len(png_bytes)} bytes", flush=True)

                texto_social = _texto_para_feed_social(texto)

                # cross-post pro Facebook e Instagram, no maximo 1x por
                # dia no TOTAL (1 gate compartilhado pelos 2 - nao 1x
                # cada, senao vira 2 "flagrante" por dia, nao 1) - e
                # conteudo de "flagrante", nao precisa de mais que isso
                url_hospedada_fd = None
                if not publicar_meta.ja_postou_falso_desconto_hoje():
                    ok_fb = publicar_meta.publicar_facebook(
                        texto_social, imagem_bytes=png_bytes)
                    url_hospedada_fd = publicar_meta.hospedar_imagem(
                        png_bytes, f"{item['product_id']}_fd.png")
                    ok_ig = url_hospedada_fd and publicar_meta.publicar_instagram(
                        texto_social, url_hospedada_fd)
                    if ok_fb or ok_ig:
                        publicar_meta.marcar_falso_desconto_postado_hoje()

                # Threads e volume alto, sem gate - todo falso desconto
                # vira post, nao so 1x/dia como no Facebook/Instagram
                try:
                    url_threads = url_hospedada_fd or publicar_meta.hospedar_imagem(
                        png_bytes, f"{item['product_id']}_fd_threads.png")
                    if url_threads:
                        publicar_threads.publicar_imagem(texto_social, url_threads)
                except Exception:
                    print("[threads] erro ao publicar falso desconto - pulando", flush=True)
                    traceback.print_exc()

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

        # Camada 1 vai pro feed E pros Stories do Facebook - a
        # deduplicacao de collector.py (nao repete produto que ficou
        # parado no mesmo preco) e o que garante que o feed nao fica
        # poluido, entao camada1 continua tendo valor la. Stories e um
        # canal a MAIS, nao substituto - tolera mais volume por ser
        # conteudo passageiro (24h), entao acompanha 1 pra 1.
        #
        # O feed (diferente da story) fica travado em 1 post/dia no
        # TOTAL - varias fotos cruas de produto por dia deixavam o
        # feed com cara de bot. Usa o cartao quadrado (catalogo),
        # nao a foto crua do Mercado Livre.
        if item.get("tipo") == "camada1" and imagem:
            texto_social = _texto_para_feed_social(texto)

            if not publicar_meta.ja_postou_feed_camada1_hoje():
                try:
                    import image_card
                    card_bytes = image_card.gerar_card_feed_oferta_real(item)
                    ok_fb_feed = publicar_meta.publicar_facebook(
                        texto_social, imagem_bytes=card_bytes)
                    url_feed = publicar_meta.hospedar_imagem(
                        card_bytes, f"{item['product_id']}_feed.png")
                    ok_ig_feed = url_feed and publicar_meta.publicar_instagram(
                        texto_social, url_feed)
                    if ok_fb_feed or ok_ig_feed:
                        publicar_meta.marcar_feed_camada1_postado_hoje()
                except Exception:
                    print("[meta] erro ao gerar/publicar cartao de feed - pulando",
                          flush=True)
                    traceback.print_exc()

            # Threads e volume alto, sem gate - toda Camada 1 vira post,
            # direto com a foto do Mercado Livre (sem gerar cartao
            # proprio - aqui e volume/alcance, nao "cara de catalogo")
            try:
                publicar_threads.publicar_imagem(texto_social, imagem)
            except Exception:
                print("[threads] erro ao publicar camada1 - pulando", flush=True)
                traceback.print_exc()

            try:
                # Stories nao aceitam legenda/link via API (confirmado
                # com teste real) - sem isso a story sairia so com a
                # foto pura, sem preco nem desconto. Por isso um cartao
                # proprio, com o texto queimado na imagem.
                import image_card
                story_bytes = image_card.gerar_story_oferta_real(item)
                publicar_meta.publicar_facebook_story(imagem_bytes=story_bytes)

                # Instagram Stories tambem so aceita image_url publica -
                # hospeda a MESMA imagem que ja foi gerada acima, sem
                # gerar de novo
                url_story = publicar_meta.hospedar_imagem(
                    story_bytes, f"{item['product_id']}_story.png")
                if url_story:
                    publicar_meta.publicar_instagram_story(url_story)
            except Exception:
                print("[meta] erro ao gerar/publicar story - pulando", flush=True)
                traceback.print_exc()

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
    ok = enviar(item, cfg, chat)

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
