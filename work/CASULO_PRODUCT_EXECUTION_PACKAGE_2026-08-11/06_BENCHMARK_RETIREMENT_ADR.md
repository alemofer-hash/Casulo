# ADR-0001 — ENCERRAR BENCHMARKS CIENTÍFICOS COMO GATE

**Status:** ACCEPTED  
**Data:** 2026-08-11  
**Decisor:** Guilherme Moura Fernandes

## Contexto

O projeto foi conduzido anteriormente como Research Preview, com campanhas de equivalência, tempo, energia, temperatura e comparação contra PyTorch. A tentativa final ficou bloqueada por condição física de refrigeração/telemetria, sem treinamento válido novo.

O objetivo mudou: construir um produto útil, local-first, voice-first e acessível, não provar uma tese científica de eficiência universal.

## Decisão

1. Encerrar imediatamente novas campanhas de benchmark científico, energético e térmico como caminho de desenvolvimento.
2. Remover S0–S7, PAPER_GAP_MATRIX, RAPL, `sched_ext`, campanhas pareadas, IC95% e instrumentação científica da definição de pronto do produto.
3. Preservar integralmente evidências, manifests, hashes e relatórios históricos em área de arquivo somente leitura.
4. Manter testes de correção, segurança, compatibilidade e desempenho interativo do produto.
5. Proibir claims comerciais quantitativos de velocidade/energia sem campanha futura separada e explicitamente autorizada.

## O que deve parar

- treinamento pareado repetitivo;
- thermal gate como gate de feature;
- watcher HWiNFO como requisito;
- calibração de `K_TCAP`/`K_Eager`;
- coleta RAPL/energia para provar economia;
- ablações para paper;
- comparação obrigatória com PyTorch;
- busca de reprodução multi-host;
- metas `>=5×`, `>=1,25×`, `>=10% joules`, `>=20% p95`;
- bloqueio do avanço por ausência de wattímetro/refrigeração.

## O que continua

- testes unitários;
- testes de equivalência semântica do compilador;
- testes de corrupção de artefato;
- segurança e isolamento;
- testes de latência de voz e cancelamento;
- testes de memória e reidratação;
- smoke tests de renderização;
- regressão de duração para impedir experiência inutilizável;
- calibração local para estimar tempo ao usuário;
- monitoramento térmico somente como proteção da máquina.

## Tratamento do histórico

Registrar sem reinterpretar:

```text
historical_speedup_median = 8.957846
historical_ci95 = [8.075179, 9.872416]
historical_pairs = 21
t_median_ms = 35.3111
eager_median_ms = 337.0635
electrical_energy_measured = false
joules = null
```

O código legado pode permanecer compilável no perfil `legacy-research`, mas:

- não roda no CI default;
- não instala dependências científicas no produto;
- não participa de release gates;
- não aparece como claim na UI/marketing;
- não é apagado.

## Migração no repositório

O Codex deve:

1. localizar o GOAL antigo e marcá-lo `SUPERSEDED_BY_PRODUCT_GOAL_2026_08_11`;
2. mover documentação científica para `docs/archive/research/` sem destruir identidade/histórico Git;
3. criar `docs/decisions/ADR-0001-product-over-benchmark.md`;
4. retirar jobs científicos do workflow padrão;
5. manter workflow manual `legacy-research` somente se seguro e necessário;
6. atualizar README e comandos default;
7. impedir execução acidental de campanha longa por comandos de produto.

## Consequências

Positivas:

- desenvolvimento deixa de depender de hardware físico específico;
- esforço converge para experiência e utilidade;
- arquitetura passa a ser avaliada por comportamento real do produto;
- evidência histórica continua honesta.

Negativas:

- nenhuma nova alegação científica de energia/desempenho será produzida;
- componentes criados apenas para pesquisa perdem prioridade;
- otimizações precisam ser justificadas por SLOs de produto, não por paper.

