# Coletor de Ofertas — Mercado Livre

Monitora preços de livros no Mercado Livre, acumula histórico e detecta
ofertas **reais** (comparadas com o próprio histórico, não com o "de/por"
inflado das lojas).

Roda de graça no GitHub Actions. Não precisa de servidor.

---

## Setup

### 1. Criar o repositório

No GitHub: **New repository** → nome `ml-deals` → **Private** → Create.

Suba estes arquivos:

```
collector.py
requirements.txt
.github/workflows/coletor.yml
README.md
```

### 2. Cadastrar os segredos

No repositório: **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**.

Cadastre um por vez:

| Nome | Valor | Quando |
|---|---|---|
| `ML_APP_ID` | ID do aplicativo do DevCenter | agora |
| `ML_APP_SECRET` | Chave secreta **nova** (após rotacionar) | agora |
| `TELEGRAM_TOKEN` | token do bot (via @BotFather) | quando criar o canal |
| `TELEGRAM_CHAT_ID` | id do canal (ex: `-1001234567890`) | quando criar o canal |
| `ML_AFFILIATE_TAG` | parâmetro de afiliado do ML | quando aprovar |

Sem os do Telegram o coletor roda normal — só não publica.

### 3. Primeiro teste

**Actions** → **Coletor de precos ML** → **Run workflow**.

Abra o log. O que esperar:

- `[auth] token obtido` → credenciais OK
- `[busca] 'livro suspense' -> 50 resultados` → API respondendo
- `[coleta] N itens unicos` → coletando
- `[hist] +N linhas` → gravando
- `[ofertas] nenhuma hoje` → **normal e esperado no início**

Depois disso, aparece a pasta `data/` com o `historico.csv`.

---

## Por que não aparece oferta nos primeiros dias

O detector exige **14 dias de histórico** por item antes de afirmar que
algo é oferta. Sem histórico, "desconto" é só o que a loja alega — e isso
mente. Com histórico, a comparação é contra o preço real praticado.

Essa espera não é desperdício: é o que vai diferenciar o canal.

---

## Como o detector funciona

Uma oferta só é anunciada se **todos** forem verdadeiros:

1. O item tem ≥ 14 dias de histórico
2. O preço de hoje está ≤ 85% da **mediana histórica** do próprio item
3. O vendedor tem reputação verde
4. O produto é **novo** (filtro aplicado já na busca)

Ajustes finos ficam no topo do `collector.py`:

```python
MIN_HISTORY_DAYS    = 14     # histórico mínimo
DEAL_DROP_THRESHOLD = 0.85   # quão abaixo da mediana
QUERIES             = [...]  # o que monitorar
```

## Expansão

Para monitorar outras categorias (não só livros), basta acrescentar termos
em `QUERIES`. A lógica de detecção é a mesma para qualquer produto.
