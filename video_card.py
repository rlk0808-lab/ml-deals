"""
Video curto (vertical, Reels/Shorts/TikTok) - PROTOTIPO.

Reaproveita o mesmo cartao ja usado no Story do Instagram
(image_card.gerar_story_oferta_real) como frame base - preco, desconto e
o CTA "grupos no link da bio" ja vem queimados na propria imagem, entao o
video manda pro site/grupos mesmo que a plataforma esconda o link da
legenda. Em cima desse frame, o ffmpeg aplica so movimento (zoom lento
tipo Ken Burns + fade de entrada/saida) - sem re-desenhar cada frame no
PIL, mais rapido e mais simples de manter.

ffmpeg vem do pacote imageio-ffmpeg (binario proprio, baixado pelo pip),
NAO depende de ffmpeg instalado no sistema - funciona igual no notebook
do Robson e no runner do GitHub Actions.
"""

import io
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

import image_card

DURACAO_S = 6
FPS = 25


def gerar_video_oferta_real(item: dict) -> bytes:
    """Recebe o mesmo dict de sempre (nome, preco, mediana, desconto,
    recorde, imagem) e devolve os bytes de um MP4 vertical (1080x1920)
    pronto pra Reels/Shorts/TikTok."""
    frame_png = image_card.gerar_story_oferta_real(item)
    frame_img = Image.open(io.BytesIO(frame_png)).convert("RGB")

    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.png"
        out_path = Path(tmp) / "saida.mp4"
        frame_img.save(frame_path)

        # SEM zoom - testamos com zoompan (Ken Burns) e o Robson nao
        # gostou: qualquer zoom corta pedaco da imagem/preco/CTA com o
        # tempo, nao tem angulo que evite cortar alguma coisa importante
        # nesse cartao especifico (foto + varios blocos de texto ate a
        # borda). So fade de entrada/saida sobre o frame parado.
        filtro = f"fade=t=in:st=0:d=0.4,fade=t=out:st={DURACAO_S - 0.5}:d=0.5"
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y",
            "-loop", "1", "-i", str(frame_path),
            "-vf", filtro, "-t", str(DURACAO_S),
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
