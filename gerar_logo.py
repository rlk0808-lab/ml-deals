"""
Gera a logo da marca a partir da MESMA identidade visual ja usada no
site e no cartao de falso desconto (fontes vendoradas em assets/fonts/,
paleta de docs/estilo.css) - nao inventa nada novo, so leva o que ja
existe pra um formato de avatar/banner.

Gera 2 arquivos em assets/logo/:
  icone.png   - 1024x1024, fundo laranja solido + marca de "check"
                organico - pensado pra avatar circular (Instagram,
                Facebook, X, Threads, TikTok cortam em circulo, entao o
                fundo vai ate a borda do quadrado de proposito)
  banner.png  - 1640x624 (razao 2.63:1, igual ao crop de desktop do
                Facebook), lockup horizontal (icone + wordmark +
                tagline) centralizado numa faixa segura contra corte
                lateral no mobile - pra capa/banner (X, Facebook)

Uso: python gerar_logo.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTE_DIR = Path(__file__).parent / "assets" / "fonts"
SAIDA = Path(__file__).parent / "assets" / "logo"

BG = (253, 252, 250)
INK = (24, 27, 22)
ACAO = (255, 90, 54)
VERIFICADO = (14, 155, 87)
CREME = (253, 252, 250)


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


def _marca_grafico(tamanho: int, cor) -> Image.Image:
    """
    O simbolo da marca: o proprio grafico de historico de preco - a
    mesma linguagem visual que aparece em CADA pagina de produto do
    site (queda real, com ruido de verdade, nao uma seta reta de
    marketing) - terminando num ponto solido, igual ao ponto de "hoje"
    do grafico real. Mais ligado ao produto do que um simbolo generico
    de "confianca". Devolve uma camada RGBA transparente.
    """
    camada = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)

    # trajetoria com ruido de verdade (sobe um pouco, desce mais) -
    # igual um historico de preco real, nao uma seta reta artificial
    pontos = [
        (0.16, 0.26),
        (0.30, 0.20),
        (0.46, 0.47),
        (0.60, 0.38),
        (0.82, 0.76),
    ]
    xy = [(x * tamanho, y * tamanho) for x, y in pontos]

    largura_traco = int(tamanho * 0.062)
    d.line(xy, fill=cor, width=largura_traco, joint="curve")
    raio = largura_traco / 2
    for px, py in xy:
        d.ellipse([px - raio, py - raio, px + raio, py + raio], fill=cor)

    # ponto final maior - o "hoje" do grafico, mesmo destaque que o
    # site da ao ultimo ponto
    px, py = xy[-1]
    raio_final = tamanho * 0.075
    d.ellipse([px - raio_final, py - raio_final, px + raio_final, py + raio_final], fill=cor)

    return camada.rotate(-4, resample=Image.BICUBIC, center=(tamanho / 2, tamanho / 2))


def gerar_icone(tamanho: int = 1024, cor_fundo=ACAO, cor_marca=CREME) -> Image.Image:
    """Avatar quadrado - fundo vai ate a borda de proposito, pra nao
    sobrar friso estranho quando a rede social cortar em circulo."""
    img = Image.new("RGB", (tamanho, tamanho), cor_fundo)
    marca = _marca_grafico(tamanho, cor_marca)
    img.paste(marca, (0, 0), marca)
    return img


def gerar_banner(largura: int = 1640, altura: int = 624) -> Image.Image:
    """
    1640x624 (razao 2.63:1) bate exatamente com o crop de desktop do
    Facebook (820x312) - zero corte lateral la. O corte agressivo
    acontece no mobile, que usa 16:9 (mais "quadrado"): pra um canvas
    2.63:1, isso corta ~16% de cada lado. Por isso todo o lockup fica
    centralizado dentro de uma faixa seguranca ainda menor que essa
    janela 16:9, com folga - assim sobrevive ao corte em qualquer
    proporcao de tela (Facebook, X, etc), em vez de ficar colado na
    borda esquerda como antes.
    """
    img = Image.new("RGB", (largura, altura), BG)
    d = ImageDraw.Draw(img)

    largura_segura = int(altura * 16 / 9 * 0.82)  # folga sobre o crop mobile (16:9)

    lado_icone = int(altura * 0.42)
    icone = Image.new("RGB", (lado_icone, lado_icone), ACAO)
    marca = _marca_grafico(lado_icone, CREME)
    icone.paste(marca, (0, 0), marca)

    mascara = Image.new("L", (lado_icone, lado_icone), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [0, 0, lado_icone - 1, lado_icone - 1], radius=int(lado_icone * 0.26), fill=255)

    # wordmark: "CAIU DE" reto + "VERDADE" italico laranja, igual ao site.
    # O tamanho da fonte e calculado pra caber no espaco que sobra da
    # zona segura (nao um valor fixo) - senao o texto fica largo demais
    # e o icone acaba empurrado pra fora da area visivel no mobile.
    gap_icone_texto = int(altura * 0.09)
    largura_disponivel_texto = largura_segura - lado_icone - gap_icone_texto

    tamanho_wordmark_ref = int(altura * 0.155)
    f_wordmark1_ref = _fonte("Fraunces-SemiBold.ttf", tamanho_wordmark_ref)
    f_wordmark2_ref = _fonte("Fraunces-BlackItalic.ttf", tamanho_wordmark_ref)
    largura_ref = (d.textlength("CAIU DE ", font=f_wordmark1_ref)
                   + d.textlength("VERDADE", font=f_wordmark2_ref))
    escala = min(1.0, largura_disponivel_texto / largura_ref)
    tamanho_wordmark = max(int(tamanho_wordmark_ref * escala), int(altura * 0.08))

    f_wordmark1 = _fonte("Fraunces-SemiBold.ttf", tamanho_wordmark)
    f_wordmark2 = _fonte("Fraunces-BlackItalic.ttf", tamanho_wordmark)
    f_tagline = _fonte("PlusJakartaSans-Bold.ttf", int(tamanho_wordmark * 0.34))

    largura_wordmark = (d.textlength("CAIU DE ", font=f_wordmark1)
                         + d.textlength("VERDADE", font=f_wordmark2))
    largura_bloco_texto = int(max(largura_wordmark, largura_disponivel_texto))
    linhas_tagline = _quebrar_texto(
        'Preço real, comparado com o histórico — não com o "de/por" da loja',
        f_tagline, largura_bloco_texto, d)

    espacamento_linha = int(tamanho_wordmark * 0.58)
    altura_texto = tamanho_wordmark + 12 + len(linhas_tagline) * espacamento_linha
    altura_bloco = max(lado_icone, altura_texto)

    x0 = (largura - (lado_icone + gap_icone_texto + largura_bloco_texto)) // 2
    y0 = (altura - altura_bloco) // 2

    img.paste(icone, (x0, y0 + (altura_bloco - lado_icone) // 2), mascara)

    x_texto = x0 + lado_icone + gap_icone_texto
    y_wordmark = y0 + (altura_bloco - altura_texto) // 2
    d.text((x_texto, y_wordmark), "CAIU DE ", font=f_wordmark1, fill=INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark1)
    d.text((x_texto + largura_prefixo, y_wordmark), "VERDADE", font=f_wordmark2, fill=ACAO)

    y_tagline = y_wordmark + tamanho_wordmark + 12
    for linha in linhas_tagline:
        d.text((x_texto, y_tagline), linha, font=f_tagline, fill=INK)
        y_tagline += espacamento_linha

    return img


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    gerar_icone(cor_fundo=ACAO, cor_marca=CREME).save(SAIDA / "icone.png")
    gerar_banner().save(SAIDA / "banner.png")
    print(f"[logo] gerado em {SAIDA}/")


if __name__ == "__main__":
    main()
