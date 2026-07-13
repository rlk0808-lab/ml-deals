"""
Gerador do site estatico (GitHub Pages) - "Caiu de Verdade".

Le os dados que o coletor ja produziu (historico.csv, watchlist.json,
ofertas.json) e gera paginas HTML puras, sem JS, uma por produto, com
grafico real de preco ao longo do tempo. Zero dependencia de API - so
usa o que ja esta commitado em data/.

Cada produto so pode reivindicar "selo verificado" se estiver em
ofertas.json de hoje (a MESMA deteccao que gera os posts do Telegram -
nao existe uma segunda logica de "oferta" so pro site. Uma fonte de
verdade so).

Uso: python site_builder.py
Gera tudo dentro de docs/ (fonte do GitHub Pages).
"""

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path

SAIDA = Path("docs")
MIN_DIAS_HIST = 14  # espelha collector.py - so pra mensagem de status


# ----------------------------------------------------------------------
# DADOS
# ----------------------------------------------------------------------

def carregar_json(caminho: Path, default):
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return default


def preco_por_dia(historico_rows: list[dict]) -> list[tuple[str, float]]:
    """1 preco por dia (o menor do dia) - mesmo criterio usado na mediana
    de deteccao, pra o grafico bater com a logica real do coletor."""
    por_dia: dict[str, float] = {}
    for r in historico_rows:
        try:
            p = float(r["preco"])
        except (ValueError, TypeError):
            continue
        data = r.get("data", "")
        if not data:
            continue
        if data not in por_dia or p < por_dia[data]:
            por_dia[data] = p
    return sorted(por_dia.items())


def link_afiliado(url: str, affiliate_tag: str) -> str:
    if affiliate_tag and url:
        return f"{url}{'&' if '?' in url else '?'}{affiliate_tag}"
    return url


def fmt_brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_data_br(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return iso


# ----------------------------------------------------------------------
# COMPONENTES SVG
# ----------------------------------------------------------------------

def caminho_suave(pontos: list[tuple[float, float]]) -> str:
    """Converte uma lista de pontos numa curva suave (Catmull-Rom -> Bezier),
    em vez de segmentos retos - fica mais organico, menos 'grafico de planilha'."""
    if len(pontos) < 3:
        return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pontos)

    p = [pontos[0]] + list(pontos) + [pontos[-1]]
    d = f"M {p[1][0]:.1f},{p[1][1]:.1f} "
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
        d += f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f} "
    return d


def caminho_selo_organico(cx: float, cy: float, raio: float) -> str:
    """Contorno fechado levemente irregular - um carimbo de verdade nunca
    e um circulo geometrico perfeito. Padrao fixo (nao aleatorio), pra o
    selo ficar sempre igual entre builds."""
    import math
    jitters = [0, 3, -2, 4, -3, 2, -4, 3, -2, 4, -3, 2, -3, 1]
    n = len(jitters)
    pontos = []
    for i, j in enumerate(jitters):
        ang = 2 * math.pi * i / n
        r = raio + j
        pontos.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))

    d = f"M {pontos[0][0]:.1f},{pontos[0][1]:.1f} "
    for i in range(n):
        p0, p1, p2, p3 = (pontos[(i - 1) % n], pontos[i % n],
                          pontos[(i + 1) % n], pontos[(i + 2) % n])
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
        d += f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f} "
    return d + "Z"


def svg_selo(texto: str) -> str:
    """O elemento de assinatura do site: um carimbo de autenticacao com
    contorno organico e levemente torto, como um documento validado de
    verdade - nao um badge de marketing generico e geometrico."""
    externo = caminho_selo_organico(75, 75, 66)
    interno = caminho_selo_organico(75, 75, 55)
    return f'''<svg class="selo" viewBox="0 0 150 150" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g transform="rotate(-9 75 75)">
    <path d="{externo}" fill="none" stroke="var(--verificado)" stroke-width="3" stroke-dasharray="5 3.5"/>
    <path d="{interno}" fill="none" stroke="var(--verificado)" stroke-width="1.5"/>
    <text x="75" y="68" text-anchor="middle" class="selo-texto">{html.escape(texto)}</text>
    <text x="75" y="88" text-anchor="middle" class="selo-sub">HISTÓRICO REAL</text>
  </g>
</svg>'''


def svg_grafico(pontos: list[tuple[str, float]], largura=680, altura=220) -> str:
    pad_x, pad_y = 40, 28
    if len(pontos) == 0:
        return '<p class="sem-dados">Ainda sem dados suficientes pra desenhar o gráfico.</p>'

    if len(pontos) == 1:
        data, preco = pontos[0]
        return (f'<div class="grafico-vazio">'
                f'<p>Só temos 1 dia de coleta até agora ({fmt_data_br(data)}): '
                f'{fmt_brl(preco)}.</p>'
                f'<p class="sem-dados">O gráfico aparece assim que houver mais dias de histórico.</p>'
                f'</div>')

    precos = [p for _, p in pontos]
    minimo, maximo = min(precos), max(precos)
    faixa = (maximo - minimo) or 1
    n = len(pontos)

    def x(i):
        return pad_x + i * (largura - 2 * pad_x) / (n - 1)

    def y(preco):
        return altura - pad_y - (preco - minimo) / faixa * (altura - 2 * pad_y)

    coords = " ".join(f"{x(i):.1f},{y(p):.1f}" for i, (_, p) in enumerate(pontos))
    pontos_xy = [(x(i), y(p)) for i, (_, p) in enumerate(pontos)]
    curva = caminho_suave(pontos_xy)
    area = curva + f" L {x(n - 1):.1f},{altura - pad_y:.1f} L {x(0):.1f},{altura - pad_y:.1f} Z"

    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(p):.1f}" r="2.5" class="grafico-ponto"/>'
        for i, (_, p) in enumerate(pontos)
    )

    # marca so o ponto de minimo historico, pra nao poluir com rotulo em cada dia
    idx_min = precos.index(minimo)
    rotulo_min = (f'<text x="{x(idx_min):.1f}" y="{y(minimo) - 10:.1f}" '
                  f'text-anchor="middle" class="grafico-rotulo-min">'
                  f'{fmt_brl(minimo)}</text>')

    data_ini, data_fim = pontos[0][0], pontos[-1][0]

    return f'''<svg class="grafico" viewBox="0 0 {largura} {altura}" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Histórico de preço de {fmt_data_br(data_ini)} a {fmt_data_br(data_fim)}">
  <line x1="{pad_x}" y1="{altura - pad_y}" x2="{largura - pad_x}" y2="{altura - pad_y}" class="grafico-eixo"/>
  <path d="{area}" class="grafico-area"/>
  <path d="{curva}" class="grafico-linha"/>
  {dots}
  {rotulo_min}
  <text x="{pad_x}" y="{altura - 6}" class="grafico-eixo-texto">{fmt_data_br(data_ini)}</text>
  <text x="{largura - pad_x}" y="{altura - 6}" text-anchor="end" class="grafico-eixo-texto">{fmt_data_br(data_fim)}</text>
</svg>'''


# ----------------------------------------------------------------------
# CSS (arquivo unico, compartilhado por todas as paginas)
# ----------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root{
  --bg:#FDFCFA; --bg-alto:#F3F5F0; --tinta:#181B16; --tinta-fraca:#6B7069;
  --verificado:#0E9B57; --verificado-fundo:#E4F6EC;
  --acao:#FF5A36; --acao-fundo:#FFEAE3;
  --pendente:#B8790A; --pendente-fundo:#FBF0DA;
  --linha:#E7E4DC; --raio:22px;
  --sombra:0 1px 2px rgba(24,27,22,.04), 0 10px 24px rgba(24,27,22,.05);
  --sombra-hover:0 4px 10px rgba(24,27,22,.06), 0 18px 34px rgba(24,27,22,.09);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--tinta);
  font-family:'IBM Plex Sans',system-ui,sans-serif; line-height:1.55;
}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace}
h1,h2,h3,.display{font-family:'Fraunces',Georgia,serif; font-weight:600; letter-spacing:-.01em}
a{color:var(--verificado)}
a.silencioso{color:inherit; text-decoration:none}
.wrap{max-width:1000px; margin:0 auto; padding:0 24px}

header.topo{padding:26px 0}
.wordmark{font-family:'JetBrains Mono',monospace; font-size:14px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--tinta); text-decoration:none}
.wordmark b{color:var(--acao)}
nav.migalha{font-size:13px; color:var(--tinta-fraca); margin:26px 0 8px}
nav.migalha a{color:var(--tinta-fraca)}

.hero{padding:40px 0 32px; position:relative; overflow:hidden}
.hero::before{content:''; position:absolute; width:460px; height:460px; z-index:-1;
  top:-200px; right:-160px; background:radial-gradient(circle, var(--acao-fundo), transparent 68%);
  border-radius:42% 58% 65% 35% / 45% 40% 60% 55%}
.hero::after{content:''; position:absolute; width:320px; height:320px; z-index:-1;
  top:40px; right:-140px; background:radial-gradient(circle, var(--verificado-fundo), transparent 70%);
  border-radius:58% 42% 35% 65% / 55% 65% 35% 45%}
.hero p.tag{color:var(--tinta-fraca); max-width:48ch; font-size:17px}
.hero h1{font-size:clamp(30px,5vw,48px); margin:8px 0 14px; line-height:1.1}

.grade-nichos{display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin:30px 0 56px}
.card-nicho{background:var(--bg-alto); border:1px solid var(--linha); border-radius:var(--raio);
  padding:26px; text-decoration:none; color:var(--tinta); display:block;
  box-shadow:var(--sombra); transition:transform .16s ease, box-shadow .16s ease}
.card-nicho:hover{transform:translateY(-3px); box-shadow:var(--sombra-hover)}
.card-nicho .emoji{font-size:30px}
.card-nicho h2{margin:12px 0 6px; font-size:22px}
.card-nicho .conta{color:var(--tinta-fraca); font-size:13.5px}
.card-nicho .conta b{color:var(--verificado)}

.como-funciona{border-top:1px solid var(--linha); padding:40px 0 60px; color:var(--tinta-fraca); font-size:14.5px}
.como-funciona ol{padding-left:20px}
.como-funciona li{margin:8px 0}

.grade-produtos{display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:16px; margin:24px 0 56px}
.card-produto{background:var(--bg-alto); border:1px solid var(--linha); border-radius:var(--raio);
  padding:18px; text-decoration:none; color:var(--tinta); display:flex; flex-direction:column; gap:9px;
  box-shadow:var(--sombra); transition:transform .16s ease, box-shadow .16s ease}
.card-produto:hover{transform:translateY(-3px); box-shadow:var(--sombra-hover)}
.card-produto img{width:100%; height:130px; object-fit:contain; background:#FFFFFF; border-radius:14px}
.card-produto .nome{font-size:14px; line-height:1.35; flex:1}
.card-produto .preco{font-family:'JetBrains Mono',monospace; font-size:18px; color:var(--acao); font-weight:500}
.tag-status{display:inline-block; font-size:11.5px; padding:4px 10px; border-radius:999px; width:fit-content; font-weight:500}
.tag-status.verificado{background:var(--verificado-fundo); color:var(--verificado)}
.tag-status.pendente{background:var(--pendente-fundo); color:var(--pendente)}

.produto-topo{display:flex; gap:32px; align-items:flex-start; padding:26px 0 10px; flex-wrap:wrap}
.selo{width:112px; flex:none}
.selo-texto{font-family:'JetBrains Mono',monospace; font-size:12px; fill:var(--verificado); font-weight:500}
.selo-sub{font-family:'JetBrains Mono',monospace; font-size:7px; fill:var(--verificado); letter-spacing:.06em}
.produto-info h1{font-size:clamp(24px,4vw,34px); margin:0 0 12px; max-width:36ch}
.preco-atual{font-family:'JetBrains Mono',monospace; font-size:38px; color:var(--acao); font-weight:500}
.preco-comparacao{color:var(--verificado); font-size:15px; margin-top:6px; font-weight:500}
.status-pendente{background:var(--pendente-fundo); color:var(--pendente); padding:11px 16px;
  border-radius:14px; font-size:14px; display:inline-block; margin-top:8px}

.grafico-bloco{margin:34px 0; background:var(--bg-alto); border:1px solid var(--linha);
  border-radius:var(--raio); padding:20px; box-shadow:var(--sombra)}
.grafico{width:100%; height:auto}
.grafico-eixo{stroke:var(--linha); stroke-width:1}
.grafico-area{fill:var(--verificado-fundo); stroke:none}
.grafico-linha{fill:none; stroke:var(--verificado); stroke-width:2.5; stroke-linecap:round}
.grafico-ponto{fill:var(--bg); stroke:var(--verificado); stroke-width:2; transition:r .12s ease}
.grafico-ponto:hover{r:5}
.grafico-rotulo-min{font-family:'JetBrains Mono',monospace; font-size:11px; fill:var(--tinta-fraca)}
.grafico-eixo-texto{font-family:'JetBrains Mono',monospace; font-size:11px; fill:var(--tinta-fraca)}
.sem-dados{color:var(--tinta-fraca); font-size:13px}
.grafico-vazio{background:var(--bg-alto); border:1px solid var(--linha); border-radius:var(--raio); padding:20px}

.estatisticas{display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin:26px 0 32px}
.estatistica{border-top:2px solid var(--verificado); padding-top:10px}
.estatistica .valor{font-family:'JetBrains Mono',monospace; font-size:22px}
.estatistica .rotulo{color:var(--tinta-fraca); font-size:12.5px}

.cta{display:inline-block; background:var(--acao); color:#FFFFFF; font-weight:600;
  text-decoration:none; padding:15px 28px; border-radius:999px; margin:12px 0 8px; font-size:15.5px;
  box-shadow:0 8px 20px rgba(255,90,54,.28); transition:transform .14s ease, box-shadow .14s ease}
.cta:hover{transform:translateY(-2px); box-shadow:0 12px 26px rgba(255,90,54,.36)}
.rodape-nota{color:var(--tinta-fraca); font-size:12.5px; border-top:1px solid var(--linha);
  margin-top:34px; padding-top:18px}

footer.rodape{border-top:1px solid var(--linha); padding:34px 0 56px; color:var(--tinta-fraca); font-size:13px}
"""


# ----------------------------------------------------------------------
# TEMPLATES DE PAGINA
# ----------------------------------------------------------------------

def base_page(titulo: str, descricao: str, corpo: str, raiz: str,
              canonical: str, json_ld: str = "") -> str:
    """raiz = caminho relativo ate a raiz do site ('.' ou '..')"""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titulo)}</title>
<meta name="description" content="{html.escape(descricao)}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="{raiz}/estilo.css">
<meta property="og:title" content="{html.escape(titulo)}">
<meta property="og:description" content="{html.escape(descricao)}">
<meta property="og:type" content="website">
{json_ld}
</head>
<body>
<header class="topo"><div class="wrap">
  <a class="wordmark" href="{raiz}/index.html">CAIU DE <b>VERDADE</b></a>
</div></header>
{corpo}
<footer class="rodape"><div class="wrap">
  Todo preço aqui vem de coleta automática comparada com o histórico real do produto.
  Nunca com o "de/por" da loja. <a href="{raiz}/index.html">Como funciona</a>.
</div></footer>
</body>
</html>"""


def pagina_home(nichos_resumo: list[dict], raiz_url: str) -> str:
    cards = "".join(f'''
    <a class="card-nicho" href="{n['slug']}/index.html">
      <div class="emoji">{n['emoji']}</div>
      <h2>{html.escape(n['nome'])}</h2>
      <div class="conta">{n['total']} produtos rastreados · <b>{n['verificados']}</b> com selo hoje</div>
    </a>''' for n in nichos_resumo)

    corpo = f'''<div class="wrap">
  <section class="hero">
    <p class="tag mono">RASTREADOR DE PREÇOS · MERCADO LIVRE</p>
    <h1>A gente não confia no "de/por" da loja.<br>A gente compara com o histórico real.</h1>
    <p class="tag">Todo produto aqui tem o preço monitorado dia após dia. Um selo só aparece
    quando o preço de hoje é comprovadamente mais baixo que o normal daquele produto -
    não porque a loja disse que é.</p>
  </section>
  <div class="grade-nichos">{cards}</div>
  <section class="como-funciona">
    <h3 style="color:var(--tinta)">Como funciona</h3>
    <ol>
      <li>Coletamos o preço de cada produto várias vezes por dia, direto na API do Mercado Livre.</li>
      <li>Depois de 14 dias de histórico, calculamos o preço mediano real daquele produto.</li>
      <li>Só quando o preço de hoje cai bem abaixo dessa mediana é que ele ganha o selo verificado.</li>
    </ol>
  </section>
</div>'''
    return base_page("Caiu de Verdade — preço real, não marketing",
                     "Comparamos o preço de hoje com o histórico real do produto no Mercado Livre, "
                     "não com o \"de/por\" fictício da loja.",
                     corpo, ".", raiz_url)


def pagina_nicho(cfg: dict, produtos: list[dict], raiz_url: str) -> str:
    cards = []
    for p in produtos:
        status = (f'<span class="tag-status verificado">selo hoje</span>' if p["verificado"]
                  else f'<span class="tag-status pendente">{p["status_txt"]}</span>')
        img = f'<img src="{p["imagem"]}" alt="" loading="lazy">' if p.get("imagem") else ""
        cards.append(f'''
    <a class="card-produto" href="{p['arquivo']}">
      {img}
      <div class="nome">{html.escape(p['nome'])}</div>
      <div class="preco mono">{fmt_brl(p['preco'])}</div>
      {status}
    </a>''')

    corpo = f'''<div class="wrap">
  <nav class="migalha"><a href="../index.html">Início</a> / {html.escape(cfg['nome'])}</nav>
  <section class="hero" style="padding-top:14px">
    <h1>{cfg['emoji']} {html.escape(cfg['nome'])}</h1>
    <p class="tag">{len(produtos)} produtos com histórico de preço monitorado.</p>
  </section>
  <div class="grade-produtos">{''.join(cards)}</div>
</div>'''
    return base_page(f"{cfg['nome']} — Caiu de Verdade",
                     f"Histórico real de preço de produtos de {cfg['nome'].lower()} no Mercado Livre.",
                     corpo, "..", raiz_url)


def pagina_produto(p: dict, cfg: dict, pontos: list[tuple[str, float]],
                   raiz_url: str) -> str:
    if p["verificado"]:
        selo_html = svg_selo("MENOR PREÇO" if p["recorde"] else "QUEDA REAL")
        status_html = (f'<div class="preco-comparacao">{p["desconto"]:.0f}% abaixo do '
                       f'preço habitual ({fmt_brl(p["mediana"])})</div>')
    else:
        selo_html = ""
        status_html = f'<div class="status-pendente">{p["status_txt"]}</div>'

    grafico_html = svg_grafico(pontos)
    dias = len(pontos)
    menor = min((v for _, v in pontos), default=p["preco"])
    data_menor = next((d for d, v in pontos if v == menor), "")

    estatisticas = f'''<div class="estatisticas">
      <div class="estatistica"><div class="valor mono">{fmt_brl(menor)}</div>
        <div class="rotulo">menor preço já registrado{f' ({fmt_data_br(data_menor)})' if data_menor else ''}</div></div>
      <div class="estatistica"><div class="valor mono">{dias}</div>
        <div class="rotulo">dias monitorados</div></div>
    </div>'''

    link_ml = link_afiliado(p["permalink"], p.get("affiliate_tag", ""))
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%M UTC")

    json_ld = f'''<script type="application/ld+json">
{json.dumps({
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": p["nome"],
        "image": p.get("imagem") or "",
        "offers": {
            "@type": "Offer",
            "priceCurrency": "BRL",
            "price": f"{p['preco']:.2f}",
            "url": link_ml,
            "availability": "https://schema.org/InStock",
        },
    }, ensure_ascii=False)}
</script>'''

    corpo = f'''<div class="wrap">
  <nav class="migalha"><a href="../index.html">Início</a> / <a href="index.html">{html.escape(cfg['nome'])}</a></nav>
  <div class="produto-topo">
    {selo_html}
    <div class="produto-info">
      <h1>{html.escape(p['nome'])}</h1>
      <div class="preco-atual mono">{fmt_brl(p['preco'])}</div>
      {status_html}
    </div>
  </div>
  <div class="grafico-bloco">{grafico_html}</div>
  {estatisticas}
  <a class="cta" href="{link_ml}" rel="nofollow sponsored" target="_blank">Ver no Mercado Livre →</a>
  <p class="rodape-nota">Preço coletado automaticamente em {agora}, comparado com o histórico
  real do produto (não com o preço "de" anunciado pela loja).</p>
</div>'''
    return base_page(f"{p['nome']} — Caiu de Verdade",
                     f"Histórico de preço de {p['nome']} no Mercado Livre: {fmt_brl(p['preco'])} hoje.",
                     corpo, "..", raiz_url, json_ld)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def montar_produto(pid: str, nome: str, permalink: str, imagem: str | None,
                   preco_hoje: float, ofertas_hoje: dict, affiliate_tag: str,
                   dias_historico: int) -> dict:
    oferta = ofertas_hoje.get(pid)
    if oferta:
        return {
            "product_id": pid, "nome": nome, "permalink": permalink,
            "imagem": imagem, "preco": preco_hoje, "affiliate_tag": affiliate_tag,
            "verificado": True, "recorde": oferta["recorde"],
            "mediana": oferta["mediana"], "desconto": oferta["desconto"],
        }
    status_txt = (f"Coletando histórico ({dias_historico}/{MIN_DIAS_HIST} dias)"
                  if dias_historico < MIN_DIAS_HIST
                  else "Hoje não é o menor preço do histórico")
    return {
        "product_id": pid, "nome": nome, "permalink": permalink,
        "imagem": imagem, "preco": preco_hoje, "affiliate_tag": affiliate_tag,
        "verificado": False, "status_txt": status_txt,
    }


def main() -> int:
    import os
    affiliate_tag = os.environ.get("ML_AFFILIATE_TAG", "").strip()
    raiz_url = os.environ.get("SITE_URL", "").strip().rstrip("/") or "."

    nichos_cfg = carregar_json(Path("config/nichos.json"), {})
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "estilo.css").write_text(CSS, encoding="utf-8")

    resumo_nichos = []
    todas_urls = []

    for slug, cfg in nichos_cfg.items():
        d = Path("data") / slug
        f_hist, f_wl, f_of = d / "historico.csv", d / "watchlist.json", d / "ofertas.json"
        if not f_hist.exists() or not f_wl.exists():
            print(f"[site] {slug}: sem dados ainda, pulando")
            continue

        wl = carregar_json(f_wl, {})
        ofertas_hoje = {o["product_id"]: o for o in carregar_json(f_of, [])}

        historico_por_produto: dict[str, list[dict]] = {}
        with f_hist.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                historico_por_produto.setdefault(row["product_id"], []).append(row)

        pasta_nicho = SAIDA / slug
        pasta_nicho.mkdir(exist_ok=True)

        produtos_pagina = []
        for pid, regs in historico_por_produto.items():
            meta = wl.get(pid)
            if not meta:
                continue  # produto saiu da watchlist, nao gera pagina morta
            pontos = preco_por_dia(regs)
            if not pontos:
                continue
            preco_hoje = pontos[-1][1]
            dias = len(pontos)

            p = montar_produto(pid, meta["nome"], meta["permalink"],
                               meta.get("imagem") or None, preco_hoje,
                               ofertas_hoje, affiliate_tag, dias)
            p["arquivo"] = f"{pid}.html"
            produtos_pagina.append(p)

            html_produto = pagina_produto(p, cfg, pontos, raiz_url)
            (pasta_nicho / f"{pid}.html").write_text(html_produto, encoding="utf-8")
            todas_urls.append(f"{raiz_url}/{slug}/{pid}.html")

        produtos_pagina.sort(key=lambda x: (not x["verificado"], x["nome"]))

        html_nicho = pagina_nicho(cfg, produtos_pagina, raiz_url)
        (pasta_nicho / "index.html").write_text(html_nicho, encoding="utf-8")
        todas_urls.append(f"{raiz_url}/{slug}/index.html")

        verificados = sum(1 for p in produtos_pagina if p["verificado"])
        resumo_nichos.append({
            "slug": slug, "nome": cfg["nome"], "emoji": cfg["emoji"],
            "total": len(produtos_pagina), "verificados": verificados,
        })
        print(f"[site] {slug}: {len(produtos_pagina)} páginas de produto "
              f"({verificados} com selo hoje)")

    (SAIDA / "index.html").write_text(pagina_home(resumo_nichos, raiz_url),
                                       encoding="utf-8")
    todas_urls.append(f"{raiz_url}/index.html")

    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
               "".join(f"  <url><loc>{u}</loc></url>\n" for u in todas_urls) +
               "</urlset>\n")
    (SAIDA / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (SAIDA / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {raiz_url}/sitemap.xml\n", encoding="utf-8")
    (SAIDA / ".nojekyll").write_text("", encoding="utf-8")

    print(f"[site] OK - {len(todas_urls)} páginas geradas em docs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
