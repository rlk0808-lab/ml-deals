"""
Recorde histórico por produto - MENOR PREÇO JÁ VISTO e QUANTOS DIAS o
produto está sendo rastreado, guardados num arquivo pequeno e separado
do historico.csv bruto.

Por que isso existe: historico.csv so cresce, para sempre (uma linha por
produto a cada rodada do coletor, ~8x/dia) - hoje ja soma dezenas de MB
por nicho e o .git do repositorio ja passa de 150MB por causa disso.
O plano e limitar historico.csv a uma janela recente (ex: 60 dias, o
suficiente pra mediana de 14 dias + o "top da semana"), mas isso
sozinho quebraria o selo "MENOR PREÇO JA REGISTRADO", que depende do
historico DESDE O PRIMEIRO DIA pra saber qual foi o menor preco de
todos os tempos.

Este arquivo resolve isso: 1 registro por produto, atualizado
incrementalmente a cada rodada (so compara o preco de hoje com o
recorde guardado - nunca precisa reler o historico inteiro), que
sobrevive independente de quantos dias de historico bruto a gente
mantiver. Formato de data/{nicho}/recordes.json:

{
  "MLB49475250": {
    "menor_preco": 169.00,
    "data_menor": "2026-08-01",
    "primeiro_dia": "2026-06-10",
    "dias_total": 53
  }
}

Diferente de camada1_state.json/camada2_state.json, este arquivo NAO e
podado quando o produto sai da watchlist. Aqueles dois sao so flags de
dedup diario - perder e inofensivo. Aqui seria destrutivo: um produto
pode sair da watchlist por um motivo temporario (esgotado por poucos
dias, mudanca de filtro em config/nichos.json) e voltar depois - se
podassemos o recorde nesse meio tempo, o preco minimo real seria
perdido pra sempre e o selo "MENOR PREÇO" poderia sair errado depois.
Como e 1 registro pequeno por produto (nao um historico crescendo por
rodada), nao ha pressao de espaço que justifique podar.
"""

import json
from datetime import date
from pathlib import Path


def carregar(d: Path) -> dict:
    f = d / "recordes.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def salvar(d: Path, recordes: dict) -> None:
    f = d / "recordes.json"
    f.write_text(json.dumps(recordes, ensure_ascii=False, indent=2), encoding="utf-8")


def atualizar(d: Path, hoje_rows: list[dict]) -> dict:
    """
    Recebe as linhas coletadas HOJE (mesmo formato que vai pro
    historico.csv - precisa ter product_id, preco, data) e atualiza o
    recorde de cada produto. Um produto so aparece aqui na primeira vez
    que e coletado - dias_total conta a partir dai, nao de antes.
    """
    recordes = carregar(d)
    for row in hoje_rows:
        pid = row["product_id"]
        preco = float(row["preco"])
        data_hoje = row["data"]
        atual = recordes.get(pid)
        if atual is None:
            recordes[pid] = {
                "menor_preco": preco,
                "data_menor": data_hoje,
                "primeiro_dia": data_hoje,
                "dias_total": 1,
                "_ultima_data_vista": data_hoje,
            }
            continue
        if data_hoje != atual.get("_ultima_data_vista"):
            atual["dias_total"] = atual.get("dias_total", 1) + (
                1 if data_hoje > atual.get("_ultima_data_vista", "") else 0)
            atual["_ultima_data_vista"] = data_hoje
        if preco < atual["menor_preco"]:
            atual["menor_preco"] = preco
            atual["data_menor"] = data_hoje
    salvar(d, recordes)
    return recordes


def backfill_de_historico(d: Path) -> int:
    """
    Reconstroi recordes.json do zero a partir do historico.csv INTEIRO -
    usado uma unica vez pra popular o arquivo com o recorde real (nao
    so o que sera coletado dai pra frente). Depois desse backfill, o
    normal e so atualizar() incrementalmente a cada rodada.
    """
    import csv
    f_hist = d / "historico.csv"
    if not f_hist.exists():
        return 0

    hist: dict[str, list[dict]] = {}
    with f_hist.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            hist.setdefault(row["product_id"], []).append(row)

    recordes = {}
    for pid, regs in hist.items():
        por_dia: dict[str, float] = {}
        for r in regs:
            try:
                p = float(r["preco"])
            except (ValueError, TypeError):
                continue
            data = r["data"]
            if data not in por_dia or p < por_dia[data]:
                por_dia[data] = p
        if not por_dia:
            continue
        dias_ordenados = sorted(por_dia)
        data_menor = min(dias_ordenados, key=lambda dd: por_dia[dd])
        recordes[pid] = {
            "menor_preco": por_dia[data_menor],
            "data_menor": data_menor,
            "primeiro_dia": dias_ordenados[0],
            "dias_total": len(dias_ordenados),
            "_ultima_data_vista": dias_ordenados[-1],
        }

    salvar(d, recordes)
    print(f"[recordes] backfill: {len(recordes)} produto(s) a partir de {f_hist}")
    return len(recordes)
