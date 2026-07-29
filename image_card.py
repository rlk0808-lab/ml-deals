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

    footer_y = ALTURA_STORY - pad - 30
    d.text((pad, footer_y), "caiudeverdade.github.io — link na bio",
           font=f_footer, fill=INK_FRACA)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
