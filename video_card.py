"""
Video curto (vertical, Reels/Shorts/TikTok) - PROTOTIPO.

Revelacao progressiva por estagios (corte seco entre cada um, sem
zoom): comeca so com a foto, depois entra o nome do produto, depois o
preco atual, e por fim o preco habitual + desconto + CTA. Testamos com
zoom (Ken Burns) sobre o cartao inteiro primeiro e o Robson nao gostou -
cortava pedaco da imagem/preco/CTA com o tempo. Cada estagio e um
frame PNG parado (mesma logica de desenho de
image_card.gerar_story_oferta_real, so que revelando por partes - o
layout de cada elemento fica sempre na MESMA posicao entre os estagios,
so o conteudo aparece, nada pula na tela).

ffmpeg vem do pacote imageio-ffmpeg (binario proprio, baixado pelo pip),
NAO depende de ffmpeg instalado no sistema - funciona igual no notebook
do Robson e no runner do GitHub Actions.
"""

import io
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
import requests
from PIL import Image, ImageDraw

import image_card

FPS = 25

# (estagio, duracao em segundos que o estagio fica parado na tela)
# 0 = so foto/wordmark/selo | 1 = +nome | 2 = +preco | 3 = +preco
# antigo/desconto/CTA (segura o resto do video, e o estado final)
ESTAGIOS = [(0, 1.3), (1, 1.1), (2, 1.1), (3, 2.5)]

# efeito "pop" (mola: passa do tamanho, volta) pro preco e o desconto -
# sao os 2 numeros que mais importam, valia destacar mais que so
# aparecer estatico igual o resto do cartao
POP_ESCALAS = [1.4, 1.15, 1.0]
POP_DURACAO_FRAME = 0.08


def _colar_texto_com_escala(img: Image.Image, texto: str, fonte,
                            pos: tuple[int, int], cor, escala: float) -> None:
    """Desenha `texto` ampliado/reduzido por `escala`, crescendo a
    partir da BORDA ESQUERDA fixa (nao do centro) - usado pro efeito de
    pop. Texto nesse cartao sempre comeca perto da borda esquerda
    (pad=64); crescer a partir do centro empurra a borda esquerda pra
    fora do quadro (testado e confirmado - cortava a tela). Vertical
    continua centrado, ha espaco de sobra pra cima/baixo."""
    medidor = ImageDraw.Draw(img)
    bbox = medidor.textbbox(pos, texto, font=fonte)
    cy = (bbox[1] + bbox[3]) / 2

    pad_patch = 12
    largura, altura = bbox[2] - bbox[0], bbox[3] - bbox[1]
    patch = Image.new("RGBA", (largura + 2 * pad_patch, altura + 2 * pad_patch), (0, 0, 0, 0))
    d_patch = ImageDraw.Draw(patch)
    d_patch.text((pad_patch - bbox[0] + pos[0], pad_patch - bbox[1] + pos[1]),
                texto, font=fonte, fill=cor)

    novo_w = max(1, round(patch.width * escala))
    novo_h = max(1, round(patch.height * escala))
    patch = patch.resize((novo_w, novo_h), Image.LANCZOS)

    # borda esquerda do TEXTO (nao do patch, que tem margem) fixa em
    # bbox[0] - a margem em volta do texto tambem escala junto
    paste_x = round(bbox[0] - pad_patch * escala)
    paste_y = round(cy - novo_h / 2)
    img.paste(patch, (paste_x, paste_y), patch)


def _montar_frame(item: dict, estagio: int, escala_pop: dict | None = None) -> Image.Image:
    """Mesmo cartao de image_card.gerar_story_oferta_real, mas so
    desenha os elementos ate `estagio` - o espaco de cada elemento e
    sempre reservado (y avança igual), so o desenho em si e condicional,
    pra nada pular de posicao quando aparece. `escala_pop` (opcional,
    ex: {"preco": 1.4}) desenha aquele elemento especifico ampliado -
    usado pra montar os frames curtos do efeito de pop."""
    escala_pop = escala_pop or {}
    pad = 64
    f_wordmark = image_card._fonte("Fraunces-BlackItalic.ttf", 30)
    f_selo = image_card._fonte("PlusJakartaSans-ExtraBold.ttf", 24)
    f_nome = image_card._fonte("PlusJakartaSans-Bold.ttf", 40)
    f_preco = image_card._fonte("PlusJakartaSans-ExtraBold.ttf", 88)
    f_preco_antigo = image_card._fonte("PlusJakartaSans-Bold.ttf", 34)
    f_desconto = image_card._fonte("PlusJakartaSans-ExtraBold.ttf", 34)
    f_footer = image_card._fonte("PlusJakartaSans-Bold.ttf", 26)

    img = Image.new("RGB", (image_card.LARGURA_STORY, image_card.ALTURA_STORY), image_card.BG)
    d = ImageDraw.Draw(img)
    y = pad

    d.text((pad, y), "CAIU DE ", font=f_wordmark, fill=image_card.INK)
    largura_prefixo = d.textlength("CAIU DE ", font=f_wordmark)
    d.text((pad + largura_prefixo, y), "VERDADE", font=f_wordmark, fill=image_card.ACAO)
    y += 74

    selo_texto = ("MENOR PREÇO JÁ REGISTRADO" if item.get("recorde") else "QUEDA REAL DE PREÇO")
    bbox = d.textbbox((0, 0), selo_texto, font=f_selo)
    selo_w = (bbox[2] - bbox[0]) + 40
    d.rounded_rectangle([pad, y, pad + selo_w, y + 52], radius=26, fill=image_card.VERIFICADO)
    d.text((pad + 20, y + 13), selo_texto, font=f_selo, fill=image_card.BRANCO)
    y += 90

    # foto - sempre desenhada, em todos os estagios (e o ponto de
    # partida do video)
    box_largura = image_card.LARGURA_STORY - 2 * pad
    box_altura = 680
    foto_y = y
    d.rounded_rectangle([pad, foto_y, pad + box_largura, foto_y + box_altura],
                        radius=32, fill=image_card.BRANCO)
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

    linhas_nome = image_card._quebrar_texto(item["nome"], f_nome,
                                            image_card.LARGURA_STORY - 2 * pad, d)[:2]
    if estagio >= 1:
        for linha in linhas_nome:
            d.text((pad, y), linha, font=f_nome, fill=image_card.INK)
            y += 50
        y += 20
    else:
        y += len(linhas_nome) * 50 + 20

    if estagio >= 2:
        texto_preco = f"R$ {item['preco']:.2f}"
        if "preco" in escala_pop:
            _colar_texto_com_escala(img, texto_preco, f_preco, (pad, y),
                                    image_card.ACAO, escala_pop["preco"])
        else:
            d.text((pad, y), texto_preco, font=f_preco, fill=image_card.ACAO)
    y += 110

    if estagio >= 3:
        d.text((pad, y), f"Preço habitual: R$ {item['mediana']:.2f}",
               font=f_preco_antigo, fill=image_card.INK_FRACA)
        y += 50
        texto_desconto = f"{item['desconto']:.0f}% abaixo do normal"
        if "desconto" in escala_pop:
            _colar_texto_com_escala(img, texto_desconto, f_desconto, (pad, y),
                                    image_card.VERIFICADO, escala_pop["desconto"])
        else:
            d.text((pad, y), texto_desconto, font=f_desconto, fill=image_card.VERIFICADO)

        cta_texto = "GRUPOS NO WHATS E TELEGRAM — LINK NA BIO"
        cta_h = 64
        bbox = d.textbbox((0, 0), cta_texto, font=f_footer)
        cta_w = (bbox[2] - bbox[0]) + 44
        cta_y = image_card.ALTURA_STORY - pad - cta_h
        d.rounded_rectangle([pad, cta_y, pad + cta_w, cta_y + cta_h],
                            radius=cta_h // 2, fill=image_card.ACAO)
        d.text((pad + 22, cta_y + 18), cta_texto, font=f_footer, fill=image_card.BRANCO)

    return img


def gerar_video_oferta_real(item: dict) -> bytes:
    """Recebe o mesmo dict de sempre (nome, preco, mediana, desconto,
    recorde, imagem) e devolve os bytes de um MP4 vertical (1080x1920)
    pronto pra Reels/Shorts/TikTok - revelacao progressiva por estagios,
    com efeito de pop no preco e no desconto quando aparecem."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out_path = tmp_path / "saida.mp4"

        entradas: list[str] = []
        idx = 0

        def _add(img: Image.Image, duracao: float) -> None:
            nonlocal idx
            p = tmp_path / f"f{idx}.png"
            img.save(p)
            entradas.extend(["-loop", "1", "-t", f"{duracao:.3f}", "-i", str(p)])
            idx += 1

        duracao_pop = len(POP_ESCALAS) * POP_DURACAO_FRAME

        for estagio, duracao in ESTAGIOS:
            chave_pop = {2: "preco", 3: "desconto"}.get(estagio)
            if chave_pop:
                for escala in POP_ESCALAS:
                    _add(_montar_frame(item, estagio, {chave_pop: escala}), POP_DURACAO_FRAME)
                _add(_montar_frame(item, estagio), max(duracao - duracao_pop, 0.3))
            else:
                _add(_montar_frame(item, estagio), duracao)

        duracao_total = sum(dur for _, dur in ESTAGIOS)
        concat_inputs = "".join(f"[{i}:v]" for i in range(idx))
        filtro_complex = (
            f"{concat_inputs}concat=n={idx}:v=1:a=0[base];"
            f"[base]fade=t=in:st=0:d=0.3,fade=t=out:st={duracao_total - 0.5}:d=0.5[outv]"
        )

        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y",
            *entradas,
            "-filter_complex", filtro_complex,
            "-map", "[outv]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path.read_bytes()


def gerar_descricao_video(item: dict, cfg: dict, raiz_url: str,
                          whatsapp_link: str, telegram_link: str) -> str:
    """Legenda do video - sempre com TODOS os links (pagina do produto,
    comunidade do WhatsApp, todos os canais do Telegram de uma vez via
    addlist), porque nem toda plataforma deixa o link clicavel aparecer
    perto do video (TikTok em especial)."""
    link_pagina = f"{raiz_url}/{cfg['slug']}/{item.get('product_id', '')}.html"
    selo = "MENOR PREÇO JÁ REGISTRADO" if item.get("recorde") else "QUEDA REAL DE PREÇO"
    # links logo no topo da legenda, antes de qualquer outra coisa - se
    # ficarem so no fim de um texto longo, passam despercebido (foi o
    # que aconteceu no primeiro protótipo)
    return (
        f"🔗 Confira e compre: {link_pagina}\n"
        f"🔗 Grupo no WhatsApp: {whatsapp_link}\n"
        f"🔗 Canal no Telegram: {telegram_link}\n\n"
        f"📉 {selo}\n\n"
        f"{item['nome']}\n"
        f"R$ {item['preco']:.2f} ({item['desconto']:.0f}% abaixo do normal)\n\n"
        f"#promocao #achadinhos #ofertas"
    )
