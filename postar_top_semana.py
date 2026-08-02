"""
"Top da semana" - post semanal (1x, disparado por cron aos domingos) com
os melhores achados REAIS dos ultimos 7 dias de cada nicho.

Decisao importante: o texto NUNCA mostra o preco. Preco muda dia a dia -
um resumo semanal com preco fixo corre o risco de estar defasado no dia
seguinte (o Robson levantou esse ponto e faz sentido). Em vez disso, o
post e so uma vitrine/curadoria ("essas pecas caíram bem essa semana") e
manda direto pra pagina do produto no site, que sempre mostra o preco
ATUAL de verdade.

Reaproveita collector.detectar() (mesma regra de oferta real de sempre -
14 dias de historico, >=15% abaixo da mediana) rodando dia a dia sobre a
janela dos ultimos 7 dias do historico.csv, em vez de duplicar a logica.

Uso: python postar_top_semana.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import collector
import links_afiliado

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
RAIZ_URL = os.environ.get("SITE_URL", "").strip().rstrip("/") or "."

DIAS_JANELA = 7
TOP_N = 5


def _melhores_da_semana(nicho: str) -> list[dict]:
    f_hist = Path("data") / nicho / "historico.csv"
    if not f_hist.exists():
        return []

    import csv
    hist: dict[str, list[dict]] = {}
    with f_hist.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            hist.setdefault(row["product_id"], []).append(row)

    hoje = datetime.now(timezone.utc).date()
    janela = {(hoje - timedelta(days=i)).isoformat() for i in range(1, DIAS_JANELA + 1)}

    melhores: dict[str, dict] = {}
    for dia in janela:
        linhas_dia = []
        for regs in hist.values():
            for r in regs:
                if r["data"] != dia:
                    continue
                try:
                    linha = dict(r)
                    linha["preco"] = float(r["preco"])
                    linhas_dia.append(linha)
                except (ValueError, TypeError):
                    continue
        if not linhas_dia:
            continue
        for o in collector.detectar(linhas_dia, hist):
            pid = o["product_id"]
            if pid not in melhores or o["desconto"] > melhores[pid]["desconto"]:
                melhores[pid] = o

    tabela_links = links_afiliado.carregar()
    candidatos = [o for o in melhores.values()
                  if links_afiliado.tem_link(o["product_id"], tabela_links)]
    candidatos.sort(key=lambda x: x["desconto"], reverse=True)
    return candidatos[:TOP_N]


def _montar_texto(nicho: str, cfg: dict, destaques: list[dict]) -> str:
    linhas = [f"{cfg['emoji']} TOP DA SEMANA - {cfg['nome'].upper()}", "",
              "Os achados que mais caíram de preço de verdade nos últimos 7 dias "
              "(preço muda todo dia - confira o valor atual em cada link):", ""]
    for o in destaques:
        link_pagina = f"{RAIZ_URL}/{cfg['slug']}/{o['product_id']}.html"
        linhas.append(f"• {o['nome'][:70]} - até {o['desconto']:.0f}% abaixo do normal essa semana")
        linhas.append(f"  {link_pagina}")
    return "\n".join(linhas)


def main() -> int:
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN nao configurado")
        return 1

    todos = json.loads(Path("config/nichos.json").read_text(encoding="utf-8"))
    ok_geral = True
    for nicho, cfg in todos.items():
        chat = os.environ.get(cfg["telegram_chat_env"], "").strip()
        if not chat:
            print(f"[top-semana] {nicho}: {cfg['telegram_chat_env']} nao configurado - pulando")
            continue

        destaques = _melhores_da_semana(nicho)
        if not destaques:
            print(f"[top-semana] {nicho}: sem destaques suficientes essa semana - pulando")
            continue

        texto = _montar_texto(nicho, cfg, destaques)
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat, "text": texto, "disable_web_page_preview": True},
            timeout=20)
        ok = r.status_code == 200
        ok_geral = ok_geral and ok
        msg_id = r.json().get("result", {}).get("message_id") if ok else None
        print(f"[top-semana] {nicho}: {'enviado' if ok else 'FALHOU'} ({r.status_code}) "
              f"{len(destaques)} destaque(s) chat_id={chat} message_id={msg_id}")

    return 0 if ok_geral else 1


if __name__ == "__main__":
    sys.exit(main())
