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
  banner.png  - 1500x500, lockup horizontal (icone + wordmark + tagline)
                pra capa/banner (X, Facebook)

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


def gerar_banner(largura: int = 1500, altura: int = 500) -> Image.Image:
    img = Image.new("RGB", (largura, altura), BG)
    d = ImageDraw.Draw(img)

    # icone pequeno a esquerda, com o mesmo fundo solido (nao circular
    # aqui - o banner nao vai ser cortado em circulo, entao mostra o
    # icone com cantos arredondados normais)
    lado_icone = int(altura * 0.62)
    icone = Image.new("RGB", (lado_icone, lado_icone), ACAO)
    marca = _marca_grafico(lado_icone, CREME)
    icone.paste(marca, (0, 0), marca)

    mascara = Image.new("L", (lado_icone, lado_icone), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [0, 0, lado_icone - 1, lado_icone - 1], radius=int(lado_icone * 0.26), fill=255)

    pad = int(altura * 0.19)
    img.paste(icone, (pad, pad), mascara)

    # wordmark: "CAIU DE" reto + "VERDADE" italico laranja, igual ao site
    x_texto = pad * 2 + lado_icone
    f_wordmark1 = _fonte("Fraunces-SemiBold.ttf", int(altura * 0.20))
    f_wordmark2 = _fonte("Fraunces-BlackItalic.ttf", int(altura * 0.20))
    f_tagline = _fonte("PlusJakartaSans-Bold.ttf", int(altura * 0.072))

    y_wordmark = int(altura * 0.28)
    d.text((x_texto, y_wordmark), "CAIU DE ", font=f_wordmark1, fill=INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark1)
    d.text((x_texto + largura_prefixo, y_wordmark), "VERDADE", font=f_wordmark2, fill=ACAO)

    largura_disponivel = largura - x_texto - pad
    linhas_tagline = _quebrar_texto(
        'Preço real, comparado com o histórico — não com o "de/por" da loja',
        f_tagline, largura_disponivel, d)
    y_tagline = int(altura * 0.60)
    for linha in linhas_tagline:
        d.text((x_texto, y_tagline), linha, font=f_tagline, fill=INK)
        y_tagline += int(altura * 0.11)

    return img


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    gerar_icone(cor_fundo=ACAO, cor_marca=CREME).save(SAIDA / "icone.png")
    gerar_banner().save(SAIDA / "banner.png")
    print(f"[logo] gerado em {SAIDA}/")


if __name__ == "__main__":
    main()
