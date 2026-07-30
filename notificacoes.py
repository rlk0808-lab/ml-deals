"""
Pedidos de acompanhamento: alguem pede pra rastrear um produto especifico
e ser avisado por e-mail quando o preco cair DE VERDADE (mesmo criterio
de detectar() em collector.py - nao "melhor preco do dia", queda real
comparada ao historico).

Fluxo:
  1. A pessoa preenche o formulario em docs/sugerir.html - cai como
     e-mail em caiudeverdade@gmail.com (via Web3Forms, sem servidor
     nenhum do nosso lado - so um POST de formulario HTML).
  2. O Robson cola o pedido em data/pedidos_novos.txt, formato:
         email | nicho | link ou ID do produto
     (mesma logica de produtos_manuais.py - pode colar link completo,
     o sistema acha o ID sozinho).
  3. O coletor importa, passa o produto pelos MESMOS filtros de sempre
     (nome, dominio, frete, min_ofertas) e comeca a rastrear (se ja nao
     estiver rastreado).
  4. Quando detectar() encontrar uma oferta REAL pra esse produto, manda
     1 e-mail e REMOVE o pedido do registro - aviso UNICO, nao assinatura
     permanente. Quem quiser ser avisado de novo, pede de novo.

LGPD: o e-mail so e usado pra esse aviso especifico, nunca repassado,
nunca vira lista de newsletter escondida - isso fica explicito no
formulario do site (docs/sugerir.html) e reforcado no rodape do proprio
e-mail de aviso.
"""

import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

NOVOS = Path("data") / "pedidos_novos.txt"
REGISTRO = Path("data") / "pedidos_notificacao.json"

NICHOS_VALIDOS = set(
    json.loads(Path("config/nichos.json").read_text(encoding="utf-8")))

GMAIL_USER = "caiudeverdade@gmail.com"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

SITE_URL = "https://rlk0808-lab.github.io/ml-deals"

_RE_MLB = re.compile(r"MLB-?(\d{8,})")
_RE_EMAIL = re.compile(r"[^\s|]+@[^\s|]+\.[^\s|]+")

_CABECALHO = (
    "# Cole aqui 1 pedido por linha, formato:\n"
    "#   email | nicho | link ou ID do produto\n"
    f"# nicho e um de: {', '.join(sorted(NICHOS_VALIDOS))}\n"
    "# Pode colar o link completo (o sistema acha o ID sozinho) ou so o ID.\n"
    "# Exemplo:\n"
    "#   fulano@gmail.com | casa | https://www.mercadolivre.com.br/p/MLB12345678\n"
    "# O coletor importa sozinho na proxima rodada e limpa o arquivo.\n"
)


# ----------------------------------------------------------------------
# REGISTRO (product_id -> lista de quem pediu aviso)
# ----------------------------------------------------------------------

def carregar() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar(registro: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# IMPORTAR PEDIDOS NOVOS (mesmo padrao de produtos_manuais.py)
# ----------------------------------------------------------------------

def importar_novos(nicho_atual: str) -> list[str]:
    """
    Le data/pedidos_novos.txt, registra o pedido (email <-> product_id)
    pros que sao deste nicho, devolve os IDs pro coletor rodar
    descobrir_de_campanha neles (garante que o produto passa a ser
    rastreado, se ainda nao for). Linhas de outros nichos ficam intactas.
    """
    try:
        bruto = NOVOS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    registro = carregar()
    restantes = []
    ids_deste_nicho = []
    hoje = datetime.now(timezone.utc).date().isoformat()

    for linha_bruta in bruto.splitlines():
        if not linha_bruta.strip() or linha_bruta.strip().startswith("#"):
            continue

        partes = [p.strip() for p in linha_bruta.split("|")]
        if len(partes) != 3:
            print(f"[pedidos] linha ignorada (formato invalido): {linha_bruta[:70]!r}")
            continue

        email, nicho, referencia = partes[0], partes[1].lower(), partes[2]
        if not _RE_EMAIL.fullmatch(email):
            print(f"[pedidos] linha ignorada (e-mail invalido): {linha_bruta[:70]!r}")
            continue
        if nicho not in NICHOS_VALIDOS:
            print(f"[pedidos] linha ignorada (nicho invalido): {linha_bruta[:70]!r}")
            continue

        m = _RE_MLB.search(referencia)
        if not m:
            print(f"[pedidos] linha ignorada (nao achei ID de produto): {linha_bruta[:70]!r}")
            continue

        if nicho != nicho_atual:
            restantes.append(linha_bruta)
            continue

        pid = f"MLB{m.group(1)}"
        pedidos_produto = registro.setdefault(pid, [])
        if not any(p["email"] == email for p in pedidos_produto):
            pedidos_produto.append({"email": email, "solicitado_em": hoje})
        ids_deste_nicho.append(pid)

    salvar(registro)

    novo_conteudo = _CABECALHO + "\n".join(restantes)
    if restantes:
        novo_conteudo += "\n"
    NOVOS.write_text(novo_conteudo, encoding="utf-8")

    return ids_deste_nicho


# ----------------------------------------------------------------------
# ENVIO
# ----------------------------------------------------------------------

def _montar_email(oferta: dict, cfg: dict) -> MIMEText:
    link_site = f"{SITE_URL}/{cfg['slug']}/{oferta['product_id']}.html"
    corpo = (
        f"O produto que você pediu pra gente ficar de olho caiu de preço de verdade:\n\n"
        f"{oferta['nome']}\n\n"
        f"Por R$ {oferta['preco']:.2f}\n"
        f"Preço habitual: R$ {oferta['mediana']:.2f}\n"
        f"{oferta['desconto']:.0f}% abaixo do normal\n\n"
        f"Veja o histórico completo e o link pra comprar: {link_site}\n\n"
        f"---\n"
        f"Você recebeu este e-mail porque pediu esse aviso especificamente pra este "
        f"produto em caiudeverdade.github.io. Não vamos te mandar mais nada além "
        f"disso - o pedido já foi removido da nossa lista. Se quiser ser avisado de "
        f"novo (deste ou de outro produto), é só pedir de novo no site."
    )
    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = f"📉 {oferta['nome'][:60]} caiu de preço de verdade"
    msg["From"] = f"Caiu de Verdade <{GMAIL_USER}>"
    return msg


def enviar_notificacoes(ofertas: list[dict], cfg: dict) -> int:
    """
    Cruza as ofertas REAIS de hoje com o registro de pedidos. Quem
    pediu aviso pra um produto que caiu de verdade recebe 1 e-mail e
    sai do registro (aviso unico, nao assinatura).
    """
    if not ofertas:
        return 0
    registro = carregar()
    if not registro:
        return 0
    if not GMAIL_APP_PASSWORD:
        print("[pedidos] GMAIL_APP_PASSWORD nao configurado - notificacao pulada")
        return 0

    enviados = 0
    servidor = None
    try:
        for oferta in ofertas:
            pid = oferta["product_id"]
            pedidos_produto = registro.get(pid)
            if not pedidos_produto:
                continue

            if servidor is None:
                servidor = smtplib.SMTP_SSL("smtp.gmail.com", 465)
                servidor.login(GMAIL_USER, GMAIL_APP_PASSWORD)

            msg = _montar_email(oferta, cfg)
            for pedido in pedidos_produto:
                msg["To"] = pedido["email"]
                try:
                    servidor.sendmail(GMAIL_USER, [pedido["email"]], msg.as_string())
                    print(f"[pedidos] avisado {pedido['email']} sobre {pid}")
                    enviados += 1
                except Exception as e:
                    print(f"[pedidos] falha ao avisar {pedido['email']}: {e}")

            del registro[pid]  # aviso unico - some do registro depois de mandar
    finally:
        if servidor:
            servidor.quit()

    if enviados:
        salvar(registro)
    return enviados
