"""
Tabela de links de afiliado gerados manualmente.

O Mercado Livre nao tem API publica para gerar link de afiliado - o link
rastreado so nasce clicando em "Compartilhar" na barra de afiliados, dentro
do site logado. Automatizar esse clique seria comportamento de bot e pode
custar a conta (1 CPF = 1 conta, sem segunda chance).

Entao: o Robson gera os links na mao (uma vez por produto, vale pra sempre)
e cadastra aqui. Todo o resto do sistema - coletor, publicador e site -
consulta esta tabela antes de montar qualquer link.

Formato de data/links_afiliado.json:

{
  "MLB54234927": {
    "link": "https://meli.la/2b2M6Yn",
    "nome": "Air Fryer Forno 25L French Door Mondial",
    "adicionado_em": "2026-07-24",
    "status": "ok",
    "ultima_checagem": "2026-07-24T13:00:00+00:00"
  }
}

status:
  ok            -> link validado, pode usar
  quebrado      -> link nao rastreia mais (nao usar, avisa o Robson)
  inconclusivo  -> a checagem nao conseguiu confirmar (ML bloqueou o
                   robo de verificacao, timeout, etc). Continua sendo
                   usado - ausencia de prova nao e prova de defeito.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ARQUIVO = Path("data") / "links_afiliado.json"

# so nao usamos o link quando temos CERTEZA que quebrou
_STATUS_INVALIDOS = {"quebrado"}


def carregar() -> dict:
    """Le a tabela. Devolve {} se ainda nao existe."""
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar(tabela: dict) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(
        json.dumps(tabela, ensure_ascii=False, indent=2), encoding="utf-8")


def tem_link(product_id: str, tabela: dict | None = None) -> bool:
    """True se este produto ja tem link rastreado utilizavel."""
    t = carregar() if tabela is None else tabela
    e = t.get(product_id)
    return bool(e and e.get("link")
                and e.get("status") not in _STATUS_INVALIDOS)


def resolver(product_id: str, permalink: str,
             tabela: dict | None = None) -> str:
    """
    Devolve o link rastreado se existir; senao o link normal do produto.

    Nunca quebra: sem link cadastrado o post sai igual, so nao rastreia.
    """
    t = carregar() if tabela is None else tabela
    e = t.get(product_id)
    if e and e.get("link") and e.get("status") not in _STATUS_INVALIDOS:
        return e["link"]
    return permalink


def resumo() -> str:
    """Linha de status para os logs."""
    t = carregar()
    ok = sum(1 for e in t.values()
             if e.get("status") not in _STATUS_INVALIDOS)
    quebrados = sum(1 for e in t.values() if e.get("status") == "quebrado")
    return f"{ok} link(s) rastreado(s) ativo(s), {quebrados} quebrado(s)"


# ----------------------------------------------------------------------
# CADASTRO SEM DOR DE CABECA
#
# O Robson nao precisa editar JSON na mao. Ele cola linhas soltas em
# data/links_novos.txt (direto pelo GitHub, sem baixar nada) e o coletor
# importa sozinho na proxima rodada.
#
# Formato aceito - uma linha por produto, tanto faz a ordem e o separador:
#   MLB54234927 https://meli.la/2b2M6Yn
#   https://meli.la/2b2M6Yn | https://www.mercadolivre.com.br/p/MLB54234927
#   MLB54234927, https://meli.la/2b2M6Yn   # comentario aqui e ignorado
# ----------------------------------------------------------------------

NOVOS = Path("data") / "links_novos.txt"

_RE_PID = re.compile(r"\b(MLB\d{5,})\b")
_RE_LINK = re.compile(r"https?://\S+")


def importar_novos() -> int:
    """
    Le data/links_novos.txt, mescla na tabela e esvazia o arquivo.
    Devolve quantos links novos entraram.
    """
    try:
        bruto = NOVOS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0

    tabela = carregar()
    hoje = datetime.now(timezone.utc).date().isoformat()
    novos = 0
    ignoradas = []

    for linha in bruto.splitlines():
        linha = linha.split("#")[0].strip()
        if not linha:
            continue

        pid = _RE_PID.search(linha)
        # o link rastreado e o que NAO e a url comum do produto
        links = [u.rstrip(".,;|") for u in _RE_LINK.findall(linha)]
        rastreado = next(
            (u for u in links if "/p/MLB" not in u and "/social/" not in u
             or "meli.la" in u), None)

        if not (pid and rastreado):
            ignoradas.append(linha[:70])
            continue

        pid = pid.group(1)
        anterior = tabela.get(pid, {})
        tabela[pid] = {
            **anterior,
            "link": rastreado,
            "nome": anterior.get("nome", ""),
            "adicionado_em": anterior.get("adicionado_em", hoje),
            "status": "ok",
            "inconclusivos_seguidos": 0,
        }
        novos += 1

    if novos:
        salvar(tabela)
        # esvazia deixando o cabecalho de instrucao
        NOVOS.write_text(
            "# Cole aqui uma linha por produto (ID + link do Compartilhar).\n"
            "# Exemplo: MLB54234927 https://meli.la/2b2M6Yn\n"
            "# O coletor importa sozinho na proxima rodada e limpa o arquivo.\n",
            encoding="utf-8")
        print(f"[links] +{novos} link(s) importado(s) de links_novos.txt")

    if ignoradas:
        print(f"[links] {len(ignoradas)} linha(s) ignorada(s) "
              f"(faltou ID do produto ou link): {ignoradas[:3]}")

    return novos


def gerar_pendentes(nicho: str, candidatos: list[dict], limite: int = 60) -> None:
    """
    Escreve data/{nicho}/links_pendentes.txt com os produtos que MAIS
    aparecem e ainda nao tem link rastreado - a fila de trabalho manual,
    ja na ordem em que da mais retorno gerar.

    Um arquivo por nicho (nao compartilhado) - senao a rodada de um
    nicho apaga a lista que a rodada anterior de outro nicho tinha
    acabado de gerar.
    """
    tabela = carregar()
    faltando = [c for c in candidatos if not tem_link(c["product_id"], tabela)]
    faltando.sort(key=lambda x: x.get("n_ofertas", 0), reverse=True)

    linhas = [
        f"PRODUTOS SEM LINK DE AFILIADO - {nicho} - por ordem de prioridade",
        "",
        "Como usar: abra o link, clique em Compartilhar na barra preta de",
        "afiliados, copie o link gerado (meli.la/...) e cole em",
        "data/links_novos.txt no formato:  MLB123456 https://meli.la/xxxx",
        "",
        f"(gerado em {datetime.now(timezone.utc).date().isoformat()})",
        "",
    ]
    for c in faltando[:limite]:
        linhas.append(f"{c['product_id']}  {c.get('nome','')[:60]}")
        linhas.append(f"    {c.get('permalink','')}")

    pendentes = Path("data") / nicho / "links_pendentes.txt"
    pendentes.parent.mkdir(parents=True, exist_ok=True)
    pendentes.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"[links] {len(faltando)} produto(s) sem link em {nicho} - "
          f"top {min(limite, len(faltando))} em {pendentes}")
