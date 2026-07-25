name: Validar links de afiliado

on:
  # Sem "schedule:" nativo de proposito - ele se mostrou pouco confiavel
  # neste repositorio. Quem dispara e o cron-job.org, 1x por dia.
  workflow_dispatch:

permissions:
  contents: write

jobs:
  validar:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -r requirements.txt

      - name: Checar links e avisar se algum quebrou
        env:
          TELEGRAM_TOKEN:      ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ADMIN: ${{ secrets.TELEGRAM_CHAT_ADMIN }}
        run: |
          git config user.name  "validador-bot"
          git config user.email "validador-bot@users.noreply.github.com"

          tentativas=3
          for i in $(seq 1 $tentativas); do
            echo "=== tentativa $i/$tentativas ==="
            git fetch origin main
            git reset --hard origin/main

            python -u validar_links.py

            git add data/
            git commit -m "validar links: $(date -u +%Y-%m-%d\ %H:%M)" || echo "nada novo"

            if git push origin main; then
              echo "=== validado e salvo com sucesso ==="
              exit 0
            fi

            echo "=== push rejeitado, tentando de novo com dados frescos ==="
            sleep $((i * 5))
          done

          echo "::error::Nao foi possivel salvar apos $tentativas tentativas"
          exit 1
