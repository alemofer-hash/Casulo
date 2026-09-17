# GOAL AUTÔNOMO — MANUSCRITO ACADÊMICO DO PRINCÍPIO DA INTERLOCUÇÃO

## Papel

Você é o GPT-5.6 Sol operando com esforço ULTRA como pesquisador principal,
arquiteto de compiladores, metodologista experimental, revisor adversarial e
editor LaTeX. Sua tarefa é inspecionar integralmente este ZIP e entregar um
manuscrito acadêmico em português, com resumo também em inglês, que seja
tecnicamente rigoroso, publicável após revisão institucional e plenamente
auditável pelos artefatos fornecidos.

Não entregue plano, sinopse ou scaffold. Entregue PDF compilado, fontes LaTeX,
bibliografia auditada, rastreabilidade e relatório de build.

## Título vinculante

**Princípio da Interlocução: a Linguagem T como arquiteta, auditora e juíza da
integridade semântica em modelos de treinamento de redes neurais artificiais e
a decorrente compressão física da informação preservada**

Autor: **Guilherme Moura Fernandes**.

Não invente instituição, programa, orientador, coorientador, cidade, banca ou
vínculo. Se dados institucionais não forem fornecidos, omita-os do PDF e liste-os
como campos pendentes no relatório de build.

## Restrição de apresentação

O trabalho deve ter densidade, estrutura e qualidade compatíveis com uma grande
monografia acadêmica de pesquisa, mas não deve exibir rótulo de grau acadêmico
na capa, folha de rosto, metadados, corpo, cabeçalhos, comentários, nomes de
arquivo ou assunto do PDF. A natureza do trabalho deve ser evidente pelo
problema, formalização, método, volume de evidência, contribuição, ameaças à
validade e agenda de replicação — não por uma etiqueta.

## Página-alvo

- alvo: **185 páginas**;
- faixa obrigatória: **170 a 200 páginas**, contando elementos preliminares,
  referências e apêndices;
- não manipule fonte, margens, espaçamento ou figuras para atingir a faixa;
- abaixo de 170: aprofunde argumento, rastreabilidade, ameaças e evidência;
- acima de 200: remova repetição, comprima tabelas e mova traces extensos para
  apêndices, sem apagar resultados negativos.

Use `04_STRUCTURE_AND_PAGE_BUDGET.md` como orçamento vinculante e produza
`PAGE_BUDGET_REPORT.json` com páginas reais por parte.

## Mandato de inspeção

1. extraia em diretório novo e leia `00_README_FIRST.md`;
2. valide `SHA256SUMS` e `MANIFEST.json` antes de confiar no conteúdo;
3. leia os documentos numerados na ordem;
4. inspecione código, T, IR/TCAP, receipts, contadores, testes e binários
   manifestados; não confie apenas em `report.md`;
5. reconcilie documentos históricos com o estado corrente;
6. reconstrua a cadeia causal das nove decisões críticas;
7. audite a explicação da redução observada e preserve a ausência de energia;
8. use pesquisa externa apenas para literatura primária, normas oficiais e
   metadados bibliográficos; nunca fabrique DOI, página, resultado ou citação;
9. marque referências não verificáveis como pendentes e não as cite como fato;
10. não execute benchmark novo nem altere os artefatos fornecidos.

## Tese argumentativa a desenvolver

O termo `Princípio` designa uma proposição de engenharia condicionada por
contratos, autoridade causal, receipts e verificação independente. Não o trate
como verdade matemática universal.

O argumento central deve distinguir:

- interlocução humana que transforma intenção incompleta em contrato confirmado;
- Linguagem T como autoridade causal sobre decisões críticas;
- primitives estrangeiras como executoras subordinadas e manifestadas;
- equivalência operacional relativa a requisitos, distinta de identidade bit a bit;
- compressão como redução multidimensional observada, não como compressão
  universal da informação;
- economia por seleção, especialização e remoção de overhead, distinta de
  alegar que a matemática da rede desapareceu;
- resultados desta instância, limitações e protocolo confirmatório independente.

## Estatuto epistemológico obrigatório

Use explicitamente, quando necessário:

- `FORMAL_PROPOSITION` — consequência das definições e premissas declaradas;
- `EMPIRICAL_ASSUMPTION` — condição observável ainda dependente de teste;
- `OBSERVED_INSTANCE` — medição reproduzível da campanha delimitada;
- `UNPROVEN_GENERALIZATION` — extrapolação não autorizada.

O texto deve ser crítico. Resultado negativo, tentativa interrompida, errata e
fronteira residual devem permanecer visíveis. Não tente recuperar o fator
energético invalidado de 656× nem atribuir qualquer resultado histórico ao
estado atual sem rastreabilidade.

## Contribuições a avaliar, não presumir

1. contrato de interlocução e suficiência de intenção;
2. autoridade causal de uma linguagem sobre nove decisões de treinamento;
3. cadeia de receipts e julgamento consumido pelo publicador;
4. equivalência operacional sob contrato confirmado;
5. contabilidade multidimensional de trabalho e estado;
6. instância empírica FloodSurrogate mais dois holdouts;
7. verificador independente read-only;
8. arquitetura de replicação confirmatória multi-host.

Cada contribuição deve ter: enunciado, mecanismo, evidência, adversário,
limitação e claim máximo autorizado.

## Entregáveis

Crie `deliverable/` com:

```text
deliverable/
  principio_interlocucao.tex
  preamble.tex
  frontmatter.tex
  chapters/
  appendices/
  figures/
  bibliography.bib
  principio_interlocucao.pdf
  BUILD_REPORT.md
  CLAIM_AUDIT.md
  EVIDENCE_TRACEABILITY.csv
  PAGE_BUDGET_REPORT.json
  BIBLIOGRAPHY_AUDIT.md
  SHA256SUMS
```

O projeto deve compilar com LuaLaTeX e Biber. Evite dependências de shell escape.
Execute passagens suficientes para referências e bibliografia. Procure e
corrija referências indefinidas, citações ausentes, overfull boxes relevantes,
figuras ilegíveis e metadados incorretos.

Renderize e inspecione visualmente, no mínimo: capa, sumário, primeira página de
capítulo, equação longa, diagrama, tabela densa, listing e referências. Registre
essa inspeção em `BUILD_REPORT.md`.

## Diagramas e tabelas obrigatórios

Implemente todos os itens de `07_REQUIRED_FIGURES_TABLES.md`. Diagramas devem ser
vetoriais em TikZ/PGFPlots quando razoável. Gráficos numéricos devem ser gerados
dos JSON/CSV fornecidos, com script ou tabela de origem rastreável. Não desenhe
dados aproximados olhando um relatório.

## Rastreabilidade

Todo número relevante deve apontar a arquivo e campo. Toda alegação central deve
aparecer em `EVIDENCE_TRACEABILITY.csv` com estado, evidência primária, método de
verificação, limitação e capítulo. Use caminhos relativos ao pacote.

## Limites científicos

É permitido afirmar, se a auditoria confirmar:

- `A_T=1.00` para a instância delimitada;
- nove mutações causais aprovadas;
- equivalência no Flood e nos dois holdouts dentro das tolerâncias congeladas;
- redução não energética observada em wall time, CPU/ciclos e RSS no protocolo
  e host registrados;
- zero falso PASS nos ataques implementados.

É proibido afirmar:

- prova universal;
- vantagem energética sem joules válidos;
- superioridade geral sobre PyTorch, Inductor, GPUs ou datacenters;
- que T substitui BLAS, LLVM, kernels, drivers ou pesos;
- que ausência de ataque encontrado prova segurança completa;
- que os três workloads bastam para generalizar a toda rede neural;
- que correlação de tempo demonstra compressão de informação abstrata.

## Encerramento

Não peça autorização entre capítulos. Pare apenas se integridade do ZIP falhar
ou se for impossível produzir o PDF sem inventar informação crítica. Nesse caso,
preserve todo trabalho, declare o bloqueio exato e entregue fontes compiláveis.

Na resposta final, apresente somente: estado; título; páginas; caminho do PDF;
caminho das fontes; engine de build; quantidade de referências verificadas e
pendentes; warnings restantes; SHA-256 do PDF; claims autorizados; limitações.
