"""
Cupons vistos em grupos publicos de afiliados, repassados pros nossos canais.
E, quando o cupom vier acompanhado de um link de "produtos selecionados"
(pagina publica do proprio Mercado Livre, tipo lista.mercadolivre.com.br/...),
usa esse link tambem como fonte extra de descoberta de produto novo.

Por que ler o GRUPO e manual, mas seguir o LINK e automatizado:
Os grupos de cupom que valem a pena sao normalmente GRUPOS PRIVADOS (link
de convite, sem @usuario publico, encaminhamento desligado de proposito -
o dono claramente nao quer o conteudo circulando pra fora). Ler isso de
forma automatizada exigiria uma conta pessoal logada via biblioteca nao
oficial, rodando o tempo todo dentro do grupo - risco pra conta pessoal
do Robson, e ignora uma escolha explicita de quem administra o grupo.

Ja o link de "produtos selecionados" que vem dentro do cupom (depois de
resolvido) cai numa pagina PUBLICA comum do proprio site do Mercado Livre
(lista.mercadolivre.com.br/...) - a mesma coisa que qualquer visitante
anonimo veria navegando o site. Isso e automatizavel do mesmo jeito que
o coletor ja busca produto via API - nao tem nada de privado ali.

⚠️ Essa parte (buscar produto a partir do link da campanha) ainda nao foi
testada contra o site de verdade - o sandbox de desenvolvimento nao
alcanca mercadolivre.com.br diretamente. As primeiras rodadas precisam
ser acompanhadas de perto pra confirmar que a extracao de produtos
funciona como esperado.

Formato de data/cupons_novos.txt - uma linha por cupom:

    nicho | codigo | texto livre descrevendo o cupom | link opcional

Exemplo:

    casa | CASA15OFF | 15% off em Casa e Decoracao, minimo R$150, ate 01/08
    moda | ROUPA20 | 20% off em roupa feminina, sem minimo, valido hoje | https://bit.ly/xxxxx

nicho precisa ser um dos existentes em config/nichos.json. O link
(4o campo) e opcional - so inclui se o cupom vier com um link de
"produtos selecionados". Nenhum campo pode conter o caractere "|".
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

NOVOS = Path("data") / "cupons_novos.txt"

# cupom de plataforma costuma durar so 1 dia - depois disso, mencionar
# ele dentro das mensagens normais (camada1/camada2/falso desconto)
# vira informacao velha/errada, entao some sozinho
DURACAO_CUPOM_ATIVO_HORAS = 24

NICHOS_VALIDOS = set(
    json.loads(Path("config/nichos.json").read_text(encoding="utf-8")))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# pega tanto MLB1234567890 (produto/item direto) quanto MLB-1234567890-
# (formato de anuncio em pagina de listagem, com traco e slug depois)
_RE_MLB = re.compile(r"MLB-?(\d{8,})")

_CABECALHO = (
    "# Cole aqui 1 cupom por linha, formato:\n"
    "#   nicho | codigo | texto livre descrevendo o cupom | link opcional\n"
    f"# nicho e um de: {', '.join(sorted(NICHOS_VALIDOS))}\n"
    "# o link (4o campo) e opcional - so inclui se o cupom tiver link de\n"
    "# \"produtos selecionados\" (o coletor busca produto novo nele tambem)\n"
    "# Exemplo:\n"
    "#   casa | CASA15OFF | 15% off em Casa e Decoracao, minimo R$150, ate 01/08\n"
    "# O coletor importa sozinho na proxima rodada e limpa o arquivo.\n"
)


def _arquivo_cupom_ativo(nicho: str) -> Path:
    return Path("data") / nicho / "cupom_ativo.json"


def salvar_cupom_ativo(nicho: str, codigo: str, texto: str) -> None:
    expira_em = datetime.now(timezone.utc) + timedelta(hours=DURACAO_CUPOM_ATIVO_HORAS)
    _arquivo_cupom_ativo(nicho).write_text(
        json.dumps({"codigo": codigo, "texto": texto,
                    "expira_em": expira_em.isoformat()}, ensure_ascii=False),
        encoding="utf-8")


def obter_cupom_ativo(nicho: str) -> dict | None:
    """Devolve {codigo, texto} se ainda tem cupom valido (< 24h desde
    que foi colado) pra esse nicho, senao None. Usado pra anexar uma
    linha de cupom nas mensagens normais - nao so no post dedicado."""
    arq = _arquivo_cupom_ativo(nicho)
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    expira_em = datetime.fromisoformat(dados["expira_em"])
    if datetime.now(timezone.utc) >= expira_em:
        return None
    return {"codigo": dados["codigo"], "texto": dados["texto"]}


def montar_cupom(codigo: str, texto: str, cfg: dict) -> str:
    """
    Tom factual e sem promessa que nao podemos garantir (Regra 2.1):
    o cupom e da PLATAFORMA, nao e algo que a gente confirma que vai
    aplicar em tal produto especifico - por isso nunca afirma preco
    final combinado, so repassa a informacao e reforca a proposta do
    canal (comparar com o historico real antes de decidir).
    """
    return (f"🎟️ {cfg['emoji']} CUPOM MERCADO LIVRE\n\n"
            f"{codigo}\n"
            f"{texto}\n\n"
            f"Vimos esse cupom circulando e resolvemos repassar. Ele é da "
            f"própria plataforma - não confirmamos se aplica em cada "
            f"produto, cada carrinho pode variar.\n\n"
            f"Antes de usar, vale conferir se o preço de hoje realmente "
            f"compensa - é pra isso que a gente rastreia o histórico "
            f"aqui no canal.")


def _linha_valida(linha: str) -> tuple[str, str, str, str] | None:
    partes = [p.strip() for p in linha.split("|")]
    if len(partes) not in (3, 4):
        return None
    nicho, codigo, texto = partes[0], partes[1], partes[2]
    link = partes[3] if len(partes) == 4 else ""
    nicho = nicho.lower()
    if nicho not in NICHOS_VALIDOS or not codigo or not texto:
        return None
    return nicho, codigo, texto, link


def resolver_produtos_da_campanha(url: str, limite: int = 100) -> list[str]:
    """
    Segue o link ate a pagina final (bit.ly -> lista.mercadolivre.com.br,
    tipicamente) e extrai os IDs de produto/anuncio mencionados nela.

    Devolve uma lista de IDs "MLB123..." - podem ser tanto o id de
    catalogo (produto) quanto o id de um anuncio especifico; quem chama
    essa funcao (collector.py) e responsavel por resolver cada um pro
    id de produto de catalogo antes de tratar como candidato de verdade.
    """
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
    except requests.RequestException as e:
        print(f"[campanha] falha ao buscar {url}: {type(e).__name__}")
        return []

    if r.status_code != 200:
        print(f"[campanha] {url} respondeu {r.status_code}, ignorando")
        return []

    ids = []
    vistos = set()
    for m in _RE_MLB.finditer(r.text):
        pid = f"MLB{m.group(1)}"
        if pid not in vistos:
            vistos.add(pid)
            ids.append(pid)
        if len(ids) >= limite:
            break

    print(f"[campanha] {url} -> {len(ids)} id(s) de produto/anuncio encontrado(s)")
    return ids


def importar_novos(nicho_atual: str, cfg: dict) -> tuple[int, list[str]]:
    """
    Le data/cupons_novos.txt, publica na FRENTE da fila do nicho quem
    bater com `nicho_atual` (cupom e urgente - nao faz sentido esperar
    a fila normal), e devolve (quantos cupons processados, ids de
    produto encontrados nos links de campanha desses cupons - pra o
    coletor rodar a descoberta neles).

    Cupons de outros nichos ficam intactos no arquivo, esperando a vez
    de rodar o coletor daquele nicho.
    """
    try:
        bruto = NOVOS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0, []

    restantes = []
    processados = 0
    ids_campanha: list[str] = []
    novos_desta_rodada: list[dict] = []  # em ordem - insere tudo de uma vez no final
    agora = datetime.now(timezone.utc).isoformat()

    for linha_bruta in bruto.splitlines():
        if not linha_bruta.strip() or linha_bruta.strip().startswith("#"):
            continue

        parsed = _linha_valida(linha_bruta)
        if not parsed:
            print(f"[cupons] linha ignorada (formato invalido): {linha_bruta[:70]!r}")
            continue

        nicho, codigo, texto, link_campanha = parsed
        if nicho != nicho_atual:
            restantes.append(linha_bruta)
            continue

        item = {
            "data": agora[:10],
            "product_id": f"cupom-{codigo}",
            "nome": f"Cupom {codigo}",
            "tipo": "cupom",
            "codigo": codigo,
            "texto_cupom": texto,
            "enfileirado_em": agora,
        }
        novos_desta_rodada.append(item)
        processados += 1

        if link_campanha:
            ids_campanha += resolver_produtos_da_campanha(link_campanha)

    if novos_desta_rodada:
        fila_path = Path("data") / nicho_atual / "fila_publicacao.json"
        try:
            fila = json.loads(fila_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fila = []
        # bloco inteiro na frente, na MESMA ordem em que apareceram no
        # arquivo (o primeiro cupom colado e o primeiro a ser publicado)
        fila = novos_desta_rodada + fila
        fila_path.write_text(json.dumps(fila, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        for item in novos_desta_rodada:
            print(f"[cupons] {item['codigo']} ({nicho_atual}) inserido na frente da fila")

        # o ultimo cupom colado nessa rodada vira o "cupom ativo" do
        # nicho (24h) - anexado nas mensagens normais, nao so no post
        # dedicado
        ultimo = novos_desta_rodada[-1]
        salvar_cupom_ativo(nicho_atual, ultimo["codigo"], ultimo["texto_cupom"])

    novo_conteudo = _CABECALHO + "\n".join(restantes)
    if restantes:
        novo_conteudo += "\n"
    NOVOS.write_text(novo_conteudo, encoding="utf-8")

    return processados, ids_campanha
