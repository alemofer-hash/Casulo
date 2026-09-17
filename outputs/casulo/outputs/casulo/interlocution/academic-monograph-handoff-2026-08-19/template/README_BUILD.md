# Projeto LaTeX

Este diretório contém uma base compilável e um exemplar editorial curto. O
agente redator deve expandi-lo para o manuscrito final, preservando o contrato
do pacote.

## Build recomendado

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Equivalente manual:

```text
lualatex -interaction=nonstopmode -halt-on-error main.tex
biber main
lualatex -interaction=nonstopmode -halt-on-error main.tex
lualatex -interaction=nonstopmode -halt-on-error main.tex
```

O exemplar não tenta atingir a paginação final. Sua função é validar tipografia,
equações, tabelas, diagrams, listings, referências e metadados.

Para ambientes Tectonic cujo bundle e Biber do sistema tenham versões
incompatíveis, `smoke.tex` seleciona BibTeX apenas para validar o layout. Essa
rota não muda o contrato do entregável final: `main.tex` continua usando Biber.
