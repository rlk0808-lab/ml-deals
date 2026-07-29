"""
Gerador do cartao de imagem "falso desconto" - a peca visual que circula
no Telegram/WhatsApp. Sem dependencia de rede na hora de gerar: as
fontes ficam vendoradas em assets/fonts/ (instancias estaticas de Plus
Jakarta Sans e Fraunces, extraidas do variable font oficial com
fonttools - as mesmas familias usadas no site, pra manter a marca
consistente). Diferente da versao anterior (que usava as fontes DejaVu
do sistema Ubuntu), vendorar garante a MESMA fonte em qualquer
ambiente, sem depender de pacote instalado no runner.

Se algo aqui falhar por qualquer motivo (fonte ausente, Pillow com erro),
quem chama isso deve capturar a excecao e cair pra mensagem de texto -
nunca deixar o post inteiro falhar por causa da imagem.
"""

import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

FONTE_DIR = Path(__file__).parent / "assets" / "fonts"

# paleta - mesma linguagem visual do site (docs/estilo.css), mas usada
# em blocos SOLIDOS aqui (nao pastel) - e conteudo de "flagrante", tem
# que chamar atencao parado no meio de fotos de produto no feed
BG = (253, 252, 250)
INK = (24, 27, 22)
INK_FRACA = (140, 144, 138)
BRANCO = (255, 255, 255)
ACAO = (255, 90, 54)
ACAO_CLARO = (255, 214, 201)
VERIFICADO = (14, 155, 87)
VERIFICADO_CLARO = (205, 243, 222)

LARGURA = 1080


def _fonte(nome: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTE_DIR / nome), tamanho)


def _quebrar_texto(texto: str, fonte, largura_max: int, draw: ImageDraw.ImageDraw) -> list[str]:
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if draw.textlength(teste, font=fonte) <= largura_max:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def _adesivo_flagrante(medidor: ImageDraw.ImageDraw) -> Image.Image:
    """
    Adesivo rotacionado tipo "fita washi" com a palavra FLAGRANTE - o
    mesmo espirito do selo organico do site (docs/estilo.css .selo),
    so que num angulo, pra reforcar o clima de "pego no flagra" sem
    depender so do texto da manchete.
    """
    fonte = _fonte("PlusJakartaSans-ExtraBold.ttf", 30)
    texto = "FLAGRANTE"
    bbox = medidor.textbbox((0, 0), texto, font=fonte)
    pad_x, pad_y = 30, 16
    w = (bbox[2] - bbox[0]) + pad_x * 2
    h = (bbox[3] - bbox[1]) + pad_y * 2
    chip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(chip)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=ACAO)
    d.text((pad_x - bbox[0], pad_y - bbox[1]), texto, font=fonte, fill=BRANCO)
    return chip.rotate(-7, expand=True, resample=Image.BICUBIC)


def gerar_cartao_falso_desconto(item: dict) -> bytes:
    """Recebe o mesmo dict que ja circula na fila (nome, preco,
    preco_original, mediana, desconto_anunciado, desconto_real,
    dias_historico) e devolve os bytes de um PNG pronto pra enviar.
    Altura calculada dinamicamente - sem sobra de espaco vazio embaixo."""
    pad = 56
    box_h = 172

    f_wordmark = _fonte("Fraunces-BlackItalic.ttf", 26)
    f_headline = _fonte("Fraunces-BlackItalic.ttf", 58)
    f_nome = _fonte("PlusJakartaSans-Bold.ttf", 32)
    f_label = _fonte("PlusJakartaSans-ExtraBold.ttf", 20)
    f_valor = _fonte("PlusJakartaSans-ExtraBold.ttf", 44)
    f_riscado = _fonte("PlusJakartaSans-Bold.ttf", 27)
    f_footer = _fonte("PlusJakartaSans-Bold.ttf", 19)

    # passo de medicao: precisa saber quantas linhas nome/manchete vao
    # ocupar antes de criar a imagem final, pra calcular a altura certa
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    linhas_nome = _quebrar_texto(item["nome"], f_nome, LARGURA - 2 * pad, medidor)[:2]
    linhas_manchete = _quebrar_texto("DESCONTO FALSO", f_headline,
                                     LARGURA - 2 * pad, medidor)

    topo_h = pad + 34 + 20 + len(linhas_manchete) * 64 + 28
    altura = (topo_h + 26 + len(linhas_nome) * 42 + 22
              + box_h + 16 + box_h + 40 + 34 + pad)

    img = Image.new("RGB", (LARGURA, altura), BG)
    d = ImageDraw.Draw(img)

    # --- faixa escura do topo: wordmark + manchete grande ---
    d.rectangle([0, 0, LARGURA, topo_h], fill=INK)
    d.text((pad, pad), "CAIU DE ", font=f_wordmark, fill=BRANCO)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark)
    d.text((pad + largura_prefixo, pad), "VERDADE", font=f_wordmark, fill=ACAO)

    y = pad + 34 + 20
    for linha in linhas_manchete:
        d.text((pad, y), linha, font=f_headline, fill=BRANCO)
        y += 64

    # --- adesivo "FLAGRANTE" rotacionado, sobre a quina da faixa escura ---
    adesivo = _adesivo_flagrante(medidor)
    img.paste(adesivo, (LARGURA - adesivo.width - 40, topo_h - adesivo.height // 2), adesivo)

    # --- nome do produto ---
    y = topo_h + 26
    for linha in linhas_nome:
        d.text((pad, y), linha, font=f_nome, fill=INK)
        y += 42
    y += 22

    # --- bloco 1: o que a loja anuncia (laranja SOLIDO, alto contraste) ---
    d.rounded_rectangle([pad, y, LARGURA - pad, y + box_h], radius=26, fill=ACAO)
    d.text((pad + 30, y + 22), "A LOJA ANUNCIA", font=f_label, fill=BRANCO)
    preco_riscado = f"R$ {item['preco_original']:.2f}"
    d.text((pad + 30, y + 58), preco_riscado, font=f_riscado, fill=ACAO_CLARO)
    largura_riscado = d.textlength(preco_riscado, font=f_riscado)
    linha_y = y + 58 + 16
    d.line([(pad + 30, linha_y), (pad + 30 + largura_riscado, linha_y)],
          fill=ACAO_CLARO, width=3)
    d.text((pad + 30, y + 95),
           f"por R$ {item['preco']:.2f}  (-{item['desconto_anunciado']:.0f}%)",
           font=f_valor, fill=BRANCO)
    y += box_h + 16

    # --- bloco 2: o que o NOSSO historico mostra (verde SOLIDO) ---
    d.rounded_rectangle([pad, y, LARGURA - pad, y + box_h], radius=26, fill=VERIFICADO)
    d.text((pad + 30, y + 22),
           f"HISTÓRICO REAL ({item['dias_historico']} DIAS)", font=f_label, fill=BRANCO)
    d.text((pad + 30, y + 58), f"R$ {item['mediana']:.2f}", font=f_valor, fill=BRANCO)
    sinal = "abaixo" if item["desconto_real"] >= 0 else "ACIMA"
    d.text((pad + 30, y + 128),
           f"hoje está só {abs(item['desconto_real']):.1f}% {sinal} do normal",
           font=f_label, fill=VERIFICADO_CLARO)
    y += box_h + 40

    d.text((pad, y), "caiudeverdade.github.io — dado real, não marketing",
           font=f_footer, fill=INK_FRACA)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------
# STORY DE OFERTA REAL (Camada 1) - formato vertical (Stories)
#
# A API de Stories do Facebook/Instagram nao aceita legenda nem link -
# so a imagem pura. Sem isso, a story sairia so com a foto do produto,
# sem preco nem desconto nenhum (testado e confirmado). Entao aqui o
# texto vai DENTRO da imagem, igual o cartao de falso desconto.
# ----------------------------------------------------------------------

LARGURA_STORY = 1080
ALTURA_STORY = 1920


def gerar_story_oferta_real(item: dict) -> bytes:
    """Recebe o mesmo dict que ja circula na fila (nome, preco, mediana,
    desconto, recorde, imagem) e devolve os bytes de um PNG vertical
    pronto pra Story."""
    pad = 64

    f_wordmark = _fonte("Fraunces-BlackItalic.ttf", 30)
    f_selo = _fonte("PlusJakartaSans-ExtraBold.ttf", 24)
    f_nome = _fonte("PlusJakartaSans-Bold.ttf", 40)
    f_preco = _fonte("PlusJakartaSans-ExtraBold.ttf", 88)
    f_preco_antigo = _fonte("PlusJakartaSans-Bold.ttf", 34)
    f_desconto = _fonte("PlusJakartaSans-ExtraBold.ttf", 34)
    f_footer = _fonte("PlusJakartaSans-Bold.ttf", 26)

    img = Image.new("RGB", (LARGURA_STORY, ALTURA_STORY), BG)
    d = ImageDraw.Draw(img)
    y = pad

    d.text((pad, y), "CAIU DE ", font=f_wordmark, fill=INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark)
    d.text((pad + largura_prefixo, y), "VERDADE", font=f_wordmark, fill=ACAO)
    y += 74

    selo_texto = ("MENOR PREÇO JÁ REGISTRADO" if item.get("recorde")
                  else "QUEDA REAL DE PREÇO")
    bbox = d.textbbox((0, 0), selo_texto, font=f_selo)
    selo_w = (bbox[2] - bbox[0]) + 40
    d.rounded_rectangle([pad, y, pad + selo_w, y + 52], radius=26, fill=VERIFICADO)
    d.text((pad + 20, y + 13), selo_texto, font=f_selo, fill=BRANCO)
    y += 90

    # foto do produto - baixa da URL do Mercado Livre; se falhar por
    # qualquer motivo, so deixa o quadro branco vazio, nunca quebra a story.
    # Caixa RETANGULAR (nao quadrada) - foto de produto costuma ser
    # vertical (capa de livro, embalagem) e sobrava muito branco vazio
    # numa caixa quadrada grande
    box_largura = LARGURA_STORY - 2 * pad
    box_altura = 680
    foto_y = y
    d.rounded_rectangle([pad, foto_y, pad + box_largura, foto_y + box_altura],
                        radius=32, fill=BRANCO)
    try:
        resp = requests.get(item["imagem"], timeout=15)
        foto = Image.open(io.BytesIO(resp.content)).convert("RGB")
        foto.thumbnail((box_largura - 60, box_altura - 60), Image.LANCZOS)
        fx = pad + (box_largura - foto.width) // 2
        fy = foto_y + (box_altura - foto.height) // 2
        img.paste(foto, (fx, fy))
    except Exception:
        pass
    y = foto_y + box_altura + 50

    linhas_nome = _quebrar_texto(item["nome"], f_nome, LARGURA_STORY - 2 * pad, d)[:2]
    for linha in linhas_nome:
        d.text((pad, y), linha, font=f_nome, fill=INK)
        y += 50
    y += 20

    d.text((pad, y), f"R$ {item['preco']:.2f}", font=f_preco, fill=ACAO)
    y += 110

    d.text((pad, y), f"Preço habitual: R$ {item['mediana']:.2f}",
           font=f_preco_antigo, fill=INK_FRACA)
    y += 50

    d.text((pad, y), f"{item['desconto']:.0f}% abaixo do normal",
           font=f_desconto, fill=VERIFICADO)

    # Story nao aceita link/legenda via API (confirmado com teste real) -
    # esse convite pros grupos so existe se estiver queimado na propria
    # imagem, por isso o CTA em destaque (nao so texto pequeno) aqui
    # embaixo, igual ao cartao institucional.
    cta_texto = "GRUPOS NO WHATS E TELEGRAM — LINK NA BIO"
    cta_h = 64
    bbox = d.textbbox((0, 0), cta_texto, font=f_footer)
    cta_w = (bbox[2] - bbox[0]) + 44
    cta_y = ALTURA_STORY - pad - cta_h
    d.rounded_rectangle([pad, cta_y, pad + cta_w, cta_y + cta_h],
                        radius=cta_h // 2, fill=ACAO)
    d.text((pad + 22, cta_y + 18), cta_texto, font=f_footer, fill=BRANCO)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------
# CARTAO DE FEED (Camada 1) - formato quadrado (1080x1080)
#
# Diferente da foto crua do produto, esse cartao da uma cara consistente
# pro feed do Facebook/Instagram ao longo do tempo - vira "catalogo",
# nao uma colagem de fotos de produto com estilo/fundo diferente cada
# uma. So 1x/dia (controlado em publicar_meta.py), diferente da Story
# (que usa a mesma logica visual mas em volume alto).
# ----------------------------------------------------------------------

LARGURA_FEED = 1080
ALTURA_FEED = 1080


def gerar_card_feed_oferta_real(item: dict) -> bytes:
    """Recebe o mesmo dict de sempre (nome, preco, mediana, desconto,
    recorde, imagem) e devolve os bytes de um PNG quadrado pro feed."""
    pad = 56

    f_wordmark = _fonte("Fraunces-BlackItalic.ttf", 24)
    f_selo = _fonte("PlusJakartaSans-ExtraBold.ttf", 20)
    f_nome = _fonte("PlusJakartaSans-Bold.ttf", 32)
    f_preco = _fonte("PlusJakartaSans-ExtraBold.ttf", 60)
    f_preco_antigo = _fonte("PlusJakartaSans-Bold.ttf", 26)
    f_desconto = _fonte("PlusJakartaSans-ExtraBold.ttf", 26)

    img = Image.new("RGB", (LARGURA_FEED, ALTURA_FEED), BG)
    d = ImageDraw.Draw(img)
    y = pad

    d.text((pad, y), "CAIU DE ", font=f_wordmark, fill=INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark)
    d.text((pad + largura_prefixo, y), "VERDADE", font=f_wordmark, fill=ACAO)
    y += 56

    selo_texto = ("MENOR PREÇO JÁ REGISTRADO" if item.get("recorde")
                  else "QUEDA REAL DE PREÇO")
    bbox = d.textbbox((0, 0), selo_texto, font=f_selo)
    selo_w = (bbox[2] - bbox[0]) + 34
    d.rounded_rectangle([pad, y, pad + selo_w, y + 44], radius=22, fill=VERIFICADO)
    d.text((pad + 17, y + 10), selo_texto, font=f_selo, fill=BRANCO)
    y += 74

    # foto do produto - caixa retangular, nao quadrada (mesma logica da
    # story: produto vertical nao deixa sobrar espaco em branco demais)
    box_largura = LARGURA_FEED - 2 * pad
    box_altura = 560
    foto_y = y
    d.rounded_rectangle([pad, foto_y, pad + box_largura, foto_y + box_altura],
                        radius=28, fill=BRANCO)
    try:
        resp = requests.get(item["imagem"], timeout=15)
        foto = Image.open(io.BytesIO(resp.content)).convert("RGB")
        foto.thumbnail((box_largura - 50, box_altura - 50), Image.LANCZOS)
        fx = pad + (box_largura - foto.width) // 2
        fy = foto_y + (box_altura - foto.height) // 2
        img.paste(foto, (fx, fy))
    except Exception:
        pass
    y = foto_y + box_altura + 34

    linhas_nome = _quebrar_texto(item["nome"], f_nome, LARGURA_FEED - 2 * pad, d)[:2]
    for linha in linhas_nome:
        d.text((pad, y), linha, font=f_nome, fill=INK)
        y += 42
    y += 12

    d.text((pad, y), f"R$ {item['preco']:.2f}", font=f_preco, fill=ACAO)
    largura_preco = d.textlength(f"R$ {item['preco']:.2f}", font=f_preco)

    # preco antigo + desconto empilhados a direita do preco grande, pra
    # caber tudo numa linha so e nao esticar a altura do cartao
    x_direita = pad + largura_preco + 24
    d.text((x_direita, y + 4), f"de R$ {item['mediana']:.2f}",
           font=f_preco_antigo, fill=INK_FRACA)
    d.text((x_direita, y + 34), f"-{item['desconto']:.0f}%",
           font=f_desconto, fill=VERIFICADO)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


LARGURA_APRESENTACAO = 1080
ALTURA_APRESENTACAO = 1350


def gerar_card_apresentacao() -> bytes:
    """
    Cartao institucional (nao depende de um item/produto) - explica o
    conceito da pagina pra quem chega pela primeira vez. Pensado pra
    ser fixado no topo do feed do Facebook/Instagram.
    """
    pad = 64
    f_wordmark = _fonte("Fraunces-BlackItalic.ttf", 26)
    f_titulo1 = _fonte("Fraunces-SemiBold.ttf", 54)
    f_titulo2 = _fonte("Fraunces-BlackItalic.ttf", 54)
    f_item_titulo = _fonte("PlusJakartaSans-ExtraBold.ttf", 30)
    f_item_corpo = _fonte("PlusJakartaSans-Bold.ttf", 26)
    f_cta = _fonte("PlusJakartaSans-ExtraBold.ttf", 28)

    img = Image.new("RGB", (LARGURA_APRESENTACAO, ALTURA_APRESENTACAO), BG)
    d = ImageDraw.Draw(img)
    y = pad

    d.text((pad, y), "CAIU DE ", font=f_wordmark, fill=INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark)
    d.text((pad + largura_prefixo, y), "VERDADE", font=f_wordmark, fill=ACAO)
    y += 76

    d.text((pad, y), "Preço que caiu", font=f_titulo1, fill=INK)
    y += 62
    d.text((pad, y), "DE VERDADE", font=f_titulo2, fill=ACAO)
    y += 90

    itens = [
        ("Comparamos com o histórico",
         "Não com o \"de/por\" inventado pela loja."),
        ("Só avisamos quando cai de verdade",
         "Preço tem que bater recorde real pra virar post."),
        ("Rastreamento todo santo dia",
         "Sem pausa, sem feriado — preço observado dia após dia."),
        ("Comunidade grátis",
         "Grupos no WhatsApp e Telegram, sem custo nenhum."),
    ]
    for titulo, corpo in itens:
        raio = 8
        cy = y + 14
        d.ellipse([pad, cy - raio, pad + raio * 2, cy + raio], fill=VERIFICADO)
        x_texto = pad + raio * 2 + 20
        d.text((x_texto, y), titulo, font=f_item_titulo, fill=INK)
        y += 40
        for linha in _quebrar_texto(corpo, f_item_corpo,
                                     LARGURA_APRESENTACAO - x_texto - pad, d):
            d.text((x_texto, y), linha, font=f_item_corpo, fill=INK_FRACA)
            y += 36
        y += 26

    y += 10
    cta_texto = "GRUPOS GRÁTIS NO LINK DA BIO"
    bbox = d.textbbox((0, 0), cta_texto, font=f_cta)
    cta_w = (bbox[2] - bbox[0]) + 48
    cta_h = 68
    d.rounded_rectangle([pad, y, pad + cta_w, y + cta_h], radius=cta_h // 2, fill=ACAO)
    d.text((pad + 24, y + 19), cta_texto, font=f_cta, fill=BRANCO)
    y += cta_h + pad

    img = img.crop((0, 0, LARGURA_APRESENTACAO, y))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
