# Inventário de conteúdo

## Incluído integralmente

- campanha `2026-08-18-interlocution-live-instance-attempt1`, exceto caches e
  diretórios temporários não selados;
- documentação `docs/research/interlocution/`;
- implementação e testes `research/interlocution/`;
- compilador T em `src/casulo/t/`;
- módulos `livelab/energy_v1` usados pelo worker e pela análise;
- full worker `2026-08-08-flood-full-worker-v1-r2`, sem o XML agregado que
  continha hostname e caminhos absolutos pessoais;
- documentos selecionados da auditoria forense, errata, unidade científica e
  arquitetura ARC/T85 necessários para interpretar a origem da pesquisa.

## Excluído deliberadamente

- GGUF, pesos neurais e runtime llama.cpp: não participam da prova causal;
- imagens/overlays de VM e releases do produto: não são objeto empírico;
- CSV HWiNFO e campanhas térmicas completas: a campanha corrente não faz claim
  energético e o histórico relevante está resumido na errata auditável;
- `__pycache__`, `.tmp`, `target`, builds, caches e arquivos intermediários;
- segredos, chaves, credenciais, dados pessoais e caminhos absolutos;
- XML agregado de testes históricos com hostname/pasta pessoal.

As exclusões reduzem exposição e duplicação sem remover a cadeia necessária
para reconstruir autoridade, equivalência, compressão não energética e limites.
