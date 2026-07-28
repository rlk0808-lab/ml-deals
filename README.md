# Caiu de Verdade — rastreador de ofertas do Mercado Livre

Monitora preços de produtos no Mercado Livre em 4 nichos (livros, bebês,
casa, moda), acumula histórico diário e só chama algo de "oferta" quando
o preço de hoje está comprovadamente abaixo do próprio histórico do
produto — nunca com base no "de/por" que a loja anuncia.

Roda de graça no GitHub Actions. Não precisa de servidor. Publica nos
canais do Telegram e gera um site estático (GitHub Pages) com o gráfico
de preço de cada produto.

---

## Arquitetura

O agendamento **não** usa o `schedule:` nativo do GitHub Actions — ele se
mostrou pouco confiável neste repositório (rodadas pulando/atrasando). Um
cron externo (cron-job.org) dispara cada workflow via `workflow_dispatch`
no horário certo.

| Script | O que faz | Disparado por |
|---|---|---|
| `collector.py` | Descobre produtos novos, coleta preço de todos os vendedores, detecta ofertas reais/falso desconto/melhor preço do dia, e enfileira o que deve ser publicado. | `coletor.yml`, algumas vezes/dia |
| `publish_next.py` | Tira 1 item da fila e publica no Telegram. Separado do coletor de propósito — publicar é barato e espaçado, pra não parecer bot cuspindo várias mensagens de uma vez. | `publicar.yml`, a cada 30 min (07h-23h30 BRT) |
| `site_builder.py` | Gera o site estático "Caiu de Verdade" (`docs/`) a partir dos dados que o coletor já produziu — zero chamada de API. | `site.yml`, sempre que o coletor termina |
| `validar_links.py` | Confere se os links de afiliado (`meli.la/...`) ainda apontam pra um produto real; avisa no Telegram se algum quebrou. | `validar_links.yml`, 1x/dia |
| `resumo_whatsapp.py` | Manda um resumo dos próximos destaques da fila pro Telegram privado, pra copiar e colar nos grupos de WhatsApp. | `resumo_whatsapp.yml`, 4x/dia |
| `links_afiliado.py` | Tabela de links de afiliado gerados manualmente (o ML não tem API pra isso — ver seção abaixo). | importado pelos outros scripts |
| `cupons.py` / `produtos_manuais.py` | Importam cupons e produtos que o Robson colou manualmente em `data/*.txt`. | importados pelo coletor |
| `abrir_pendentes.py` | Abre em lote as abas dos produtos sem link de afiliado, pra agilizar o clique manual em "Compartilhar". | rodado manualmente pelo Robson |
| `image_card.py` / `testar_cartao.py` | Gera o cartão de imagem (Pillow) usado nos posts de "falso desconto"; o segundo só testa isso no ambiente real. | usado por `publish_next.py` |

## Setup

### Segredos (Settings → Secrets and variables → Actions)

| Nome | Valor |
|---|---|
| `ML_APP_ID` / `ML_APP_SECRET` | credenciais do app no DevCenter do Mercado Livre |
| `TELEGRAM_TOKEN` | token do bot (via @BotFather) |
| `TELEGRAM_CHAT_LIVROS` / `_BEBES` / `_CASA` / `_MODA` | id de cada canal público |
| `TELEGRAM_CHAT_ADMIN` | id do chat privado do Robson (resumos e avisos) |

Sem os do Telegram o coletor roda normal — só não publica.

### Primeiro teste

**Actions** → **Coletor de ofertas ML** → **Run workflow**. No log:

- `[auth] token OK` → credenciais certas
- `[descoberta] +N novos` → API respondendo
- `[coleta] N/M produtos com oferta aprovada` → coletando de verdade
- `[hist] +N linhas` → gravando
- `[ofertas] nenhuma` → **normal e esperado nos primeiros dias**

---

## Por que não aparece oferta nos primeiros dias

O detector exige **14 dias de histórico** por produto antes de afirmar
que algo é oferta (`MIN_DIAS_HIST` em `collector.py`). Sem histórico,
"desconto" é só o que a loja alega — e isso mente. Com histórico, a
comparação é contra o preço mediano real praticado por aquele produto.

## Como o detector funciona (3 camadas)

1. **Oferta real** (`detectar`) — produto com ≥14 dias de histórico e
   preço de hoje ≤ 85% da mediana histórica (`LIMIAR_QUEDA`).
2. **Melhor preço hoje** (`detectar_camada2`) — roda 1x/dia, pra o canal
   não ficar mudo enquanto o histórico de 14 dias não fecha. Nunca afirma
   queda, só informa o menor preço entre vendedores.
3. **Falso desconto** (`detectar_falso_desconto`) — expõe quando a loja
   anuncia um "de/por" vistoso mas o histórico real mostra que o preço
   não mudou. Limitado a poucos posts/dia (é conteúdo de "flagrante").

Os filtros de qualidade (produto novo, sem importado, frete grátis,
idioma, mínimo de vendedores concorrentes) ficam em `config/nichos.json`,
um bloco por nicho — inclusive as buscas (`queries`) que alimentam a
descoberta de produto novo.

## Como funcionam os links de afiliado

O Mercado Livre não tem API pública pra gerar link de afiliado — o link
rastreado só nasce clicando em "Compartilhar" na barra de afiliados,
dentro do site logado. Automatizar esse clique seria comportamento de
bot e pode custar a conta.

Fluxo manual: o Robson gera o link (`abrir_pendentes.py` ajuda a abrir os
produtos pendentes em lote), cola `MLB123456 https://meli.la/xxxx` em
`data/links_novos.txt`, e `links_afiliado.importar_novos()` mescla na
tabela (`data/links_afiliado.json`) na próxima rodada. `validar_links.py`
confere diariamente se os links continuam válidos.

## Expansão

Pra monitorar um nicho novo, adiciona um bloco em `config/nichos.json`
(nome, emoji, filtros, `queries`) e a variável `TELEGRAM_CHAT_<NICHO>`
correspondente. A lógica de coleta/detecção é a mesma pra qualquer nicho.
