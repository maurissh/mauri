name: Aggiorna Lista Tivusat

on:
  schedule:
    - cron: '0 4 * * *'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout del repository
        uses: actions/checkout@v3

      - name: Configura Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.x'

      - name: Esegui lo script Python
        run: python update_list.py

      - name: Committa e pusha i cambiamenti
        run: |
          git config --global user.name "GitHub Action Bot"
          git config --global user.email "action@github.com"
          git add tivusat_ordinato.m3u
          git diff --quiet && git diff --staged --quiet || (git commit -m "Aggiornamento lista Tivùsat" && git push)
