"""
Produtos que o Robson achou navegando manualmente (ex: abrindo o link de
uma campanha de cupom e vendo que tem varios itens bons pro nicho) e quer
que o sistema passe a rastrear.

Por que isso e melhor que tentar ler a pagina de campanha sozinho:
Tentamos buscar a pagina de campanha automaticamente (resolver_produtos_da_campanha
em cupons.py) e ela voltou vazia - o Mercado Livre (ou o encurtador no meio
do caminho) parece bloquear acesso que nao vem de um navegador de verdade.
Nao vale a pena resolver isso com um navegador automatizado rodando o tempo
todo, so pra economizar um copiar-e-colar.

Entao o modelo e: o Robson ja esta olhando os produtos de qualquer forma
(pra ver se sao bons) - so precisa colar o link dos que valem a pena aqui.
O sistema faz o resto sozinho: busca o preco de verdade, aplica os MESMOS
filtros de qualidade de sempre (nome, dominio, frete, min_ofertas), e so
adiciona na watchlist quem passar.

Formato de data/produtos_novos.txt - um produto por linha:

    nicho | link ou ID do produto

Exemplo:

    moda | https://www.mercadolivre.com.br/camiseta-x/p/MLB12345678
    casa | MLB98765432

nicho precisa ser um dos 4 existentes (livros/bebes/casa/moda). Pode
colar o link completo (o sistema extrai o ID sozinho) ou so o ID.
"""

import re
from pathlib import Path

NOVOS = Path("data") / "produtos_novos.txt"

NICHOS_VALIDOS = {"livros", "bebes", "casa", "moda"}

_RE_MLB = re.compile(r"MLB-?(\d{8,})")

_CABECALHO = (
    "# Cole aqui 1 produto por linha, formato:\n"
    "#   nicho | link ou ID do produto\n"
    "# nicho e um de: livros, bebes, casa, moda\n"
    "# Pode colar o link completo (o sistema acha o ID sozinho) ou so o ID.\n"
    "# Exemplo:\n"
    "#   moda | https://www.mercadolivre.com.br/camiseta-x/p/MLB12345678\n"
    "# O coletor importa sozinho na proxima rodada e limpa o arquivo.\n"
)


def importar_novos(nicho_atual: str) -> list[str]:
    """
    Le data/produtos_novos.txt, devolve os IDs de produto/anuncio que sao
    deste nicho (pra o coletor rodar descobrir_de_campanha neles), e
    remove essas linhas do arquivo. Linhas de outros nichos ficam
    intactas, esperando a vez do proprio nicho.
    """
    try:
        bruto = NOVOS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    restantes = []
    ids_deste_nicho = []

    for linha_bruta in bruto.splitlines():
        if not linha_bruta.strip() or linha_bruta.strip().startswith("#"):
            continue

        partes = [p.strip() for p in linha_bruta.split("|")]
        if len(partes) != 2:
            print(f"[produtos] linha ignorada (formato invalido): {linha_bruta[:70]!r}")
            continue

        nicho, referencia = partes[0].lower(), partes[1]
        if nicho not in NICHOS_VALIDOS:
            print(f"[produtos] linha ignorada (nicho invalido): {linha_bruta[:70]!r}")
            continue

        m = _RE_MLB.search(referencia)
        if not m:
            print(f"[produtos] linha ignorada (nao achei ID de produto): {linha_bruta[:70]!r}")
            continue

        if nicho != nicho_atual:
            restantes.append(linha_bruta)
            continue

        ids_deste_nicho.append(f"MLB{m.group(1)}")

    novo_conteudo = _CABECALHO + "\n".join(restantes)
    if restantes:
        novo_conteudo += "\n"
    NOVOS.write_text(novo_conteudo, encoding="utf-8")

    return ids_deste_nicho
