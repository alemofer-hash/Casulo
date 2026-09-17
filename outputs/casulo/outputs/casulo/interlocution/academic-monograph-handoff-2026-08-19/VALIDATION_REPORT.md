# Validação do handoff

Data: 2026-08-19.

## Código e evidência

- suíte focal: `research/interlocution/tests`;
- resultado final: `30 passed in 5.44s`;
- ambiente: Python com `PYTHONPATH=src;research/interlocution`;
- primeira tentativa: bloqueada por `WinError 5` na pasta temporária global do
  Windows; não foi classificada como falha do código;
- repetição: `TMP`, `TEMP` e `--basetemp` isolados, todos os testes aprovados;
- nenhum benchmark, treinamento ou medição energética novo foi iniciado.

## LaTeX e PDF

- exemplar: `template/smoke.pdf`;
- páginas: 25;
- formato: A4;
- engine: Tectonic 0.17.0;
- bibliografia do smoke: BibTeX, como fallback portátil;
- contrato final preservado: LuaLaTeX + Biber;
- páginas inspecionadas: capa, resumo, sumário, capítulo 1, formulação e diagrama,
  tabela/listing, gráfico, apêndice e referências;
- defeitos bloqueantes: zero;
- avisos residuais: URLs extensas e uma célula com espaçamento frouxo no
  exemplar; o GOAL exige correção de warnings relevantes no PDF final.

## Privacidade e alegações

- zero padrão de chave/token conhecido no scan textual;
- zero caminho absoluto pessoal no pacote;
- zero rótulo explícito de grau acadêmico no scan case-insensitive;
- pesos, VMs, caches e CSV de telemetria não foram incluídos;
- energia permanece não medida;
- o resultado invalidado de 656× aparece somente como histórico a não reutilizar.

## Integridade

`MANIFEST.json` e `SHA256SUMS` são gerados depois desta validação e conferidos
por `tools/verify_package.py`. O ZIP final é extraído em diretório novo e
verificado novamente antes da entrega.
