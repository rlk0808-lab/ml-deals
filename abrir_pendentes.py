"""
Abre em abas do navegador os produtos sem link de afiliado de um nicho,
pra agilizar o processo manual: o Robson so precisa clicar em
"Compartilhar" em cada aba (logado na conta dele) e colar os links
gerados de volta no chat.

NAO automatiza o clique em "Compartilhar" nem faz login nenhum - so abre
URL, a mesma coisa que abrir manualmente uma por uma, so que em lote.
Automatizar o clique em si e que seria comportamento de bot (ver aviso
em links_afiliado.py) - isso aqui continua 100% manual do lado do ML.

Uso:  python abrir_pendentes.py <nicho> [quantidade]
      python abrir_pendentes.py livros 15
"""

import re
import sys
import time
import webbrowser
from pathlib import Path

_RE_PID = re.compile(r"^(MLB\d+)\s")

PAUSA_ENTRE_ABAS = 0.4  # evita sobrecarregar o navegador abrindo tudo de uma vez


def ler_pendentes(nicho: str) -> list[tuple[str, str]]:
    f = Path("data") / nicho / "links_pendentes.txt"
    if not f.exists():
        print(f"[!] {f} nao existe - roda o coletor desse nicho primeiro")
        return []

    linhas = f.read_text(encoding="utf-8").splitlines()
    itens = []
    for i, linha in enumerate(linhas):
        m = _RE_PID.match(linha)
        if m and i + 1 < len(linhas):
            url = linhas[i + 1].strip()
            itens.append((m.group(1), url))
    return itens


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python abrir_pendentes.py <nicho> [quantidade]")
        return 1

    nicho = sys.argv[1]
    qtd = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    itens = ler_pendentes(nicho)[:qtd]
    if not itens:
        print(f"[abrir] nada pendente em {nicho}")
        return 0

    print(f"[abrir] {len(itens)} produto(s) de {nicho}:\n")
    for pid, url in itens:
        print(f"  {pid}  {url}")
        webbrowser.open_new_tab(url)
        time.sleep(PAUSA_ENTRE_ABAS)

    print("\nDepois de clicar em Compartilhar em cada aba, cola aqui no chat:")
    print("  MLB123456 https://meli.la/xxxx  (uma linha por produto)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
