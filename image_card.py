"""
Gerador do cartao de imagem "falso desconto" - a peca visual que circula
no WhatsApp. Usa Pillow + fontes DejaVu, que ja vem instaladas por padrao
no runner Ubuntu do GitHub Actions (fonts-dejavu-core). Sem dependencia
de rede, sem arquivo de fonte pra versionar no repo.

Se algo aqui falhar por qualquer motivo (fonte ausente, Pillow com erro),
quem chama isso deve capturar a excecao e cair pra mensagem de texto -
nunca deixar o post inteiro falhar por causa da imagem.
"""

import io

from PIL import Image, ImageDraw, ImageFont

FONTE_DIR = "/usr/share/fonts/truetype/dejavu"

# paleta - mesma linguagem visual do site (docs/estilo.css)
BG = (253, 252, 250)
INK = (24, 27, 22)
INK_FRACA = (107, 112, 105)
PENDENTE = (184, 121, 10)
PENDENTE_BG = (251, 240, 218)
VERIFICADO = (14, 155, 87)
VERIFICADO_BG = (228, 246, 236)

LARGURA = 1080


def _fonte(nome: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(f"{FONTE_DIR}/{nome}", tamanho)


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


def gerar_cartao_falso_desconto(item: dict, cfg: dict) -> bytes:
    """Recebe o mesmo dict que ja circula na fila (nome, preco,
    preco_original, mediana, desconto_anunciado, desconto_real,
    dias_historico) e devolve os bytes de um PNG pronto pra enviar.
    Altura calculada dinamicamente - sem sobra de espaco vazio embaixo."""
    pad = 64
    box_h = 210

    f_wordmark = _fonte("DejaVuSansMono-Bold.ttf", 26)
    f_headline = _fonte("DejaVuSans-Bold.ttf", 42)
    f_nome = _fonte("DejaVuSerif-Bold.ttf", 36)
    f_label = _fonte("DejaVuSansMono-Bold.ttf", 22)
    f_valor = _fonte("DejaVuSansMono-Bold.ttf", 52)
    f_footer = _fonte("DejaVuSansMono.ttf", 20)

    # passo de medicao: precisa saber quantas linhas o nome vai ocupar
    # antes de criar a imagem final, pra calcular a altura certa
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    linhas_nome = _quebrar_texto(item["nome"], f_nome, LARGURA - 2 * pad, medidor)[:2]

    altura = (pad + 56 + 66 + len(linhas_nome) * 46 + 26
              + box_h + 22 + box_h + 40 + 40 + pad)

    img = Image.new("RGB", (LARGURA, altura), BG)
    d = ImageDraw.Draw(img)
    y = pad

    d.text((pad, y), "CAIU DE VERDADE", font=f_wordmark, fill=INK)
    y += 56

    d.text((pad, y), "DE OLHO NO \"DESCONTO\"", font=f_headline, fill=INK)
    y += 66

    for linha in linhas_nome:
        d.text((pad, y), linha, font=f_nome, fill=INK)
        y += 46
    y += 26

    # bloco 1 - o que a loja anuncia (cor "pendente" = alegacao nao confirmada)
    d.rounded_rectangle([pad, y, LARGURA - pad, y + box_h], radius=26, fill=PENDENTE_BG)
    d.text((pad + 32, y + 26), "A LOJA ANUNCIA", font=f_label, fill=PENDENTE)
    d.text((pad + 32, y + 66),
           f"de R$ {item['preco_original']:.2f} por R$ {item['preco']:.2f}",
           font=f_valor, fill=INK)
    d.text((pad + 32, y + box_h - 46),
           f"-{item['desconto_anunciado']:.0f}% (alegado)", font=f_label, fill=PENDENTE)
    y += box_h + 22

    # bloco 2 - o que o NOSSO historico mostra (verde = dado verificado)
    d.rounded_rectangle([pad, y, LARGURA - pad, y + box_h], radius=26, fill=VERIFICADO_BG)
    d.text((pad + 32, y + 26),
           f"NOSSO HISTÓRICO REAL ({item['dias_historico']} DIAS)",
           font=f_label, fill=VERIFICADO)
    d.text((pad + 32, y + 66), f"R$ {item['mediana']:.2f}", font=f_valor, fill=INK)
    sinal = "abaixo" if item["desconto_real"] >= 0 else "ACIMA"
    d.text((pad + 32, y + box_h - 46),
           f"hoje está {abs(item['desconto_real']):.1f}% {sinal} do normal",
           font=f_label, fill=VERIFICADO)
    y += box_h + 40

    # sem emoji aqui - DejaVu nao tem glifo de emoji, vira quadrado quebrado
    d.text((pad, y), "caiudeverdade — histórico real, não marketing",
           font=f_footer, fill=INK_FRACA)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
