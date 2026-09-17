# Blueprint confirmatório independente

## Objetivo

Separar definitivamente dois efeitos:

1. autoridade causal de T sobre decisões críticas;
2. custo do stack de execução escolhido sob trabalho equivalente.

Nenhum único benchmark deve misturar essas perguntas sem ablação.

## Pré-registro

Antes de resultados, congelar: commits, hashes, workloads, datasets, seeds,
primitives, ABIs, versões, afinidade, threads, ordem, critérios de rejeição,
tolerâncias, métricas primárias, potência estatística e scripts de análise.

## Braços

- A: baseline transparente sem T;
- B: T somente auditora, julgamento ignorado para publicação;
- C: T arquiteta, sem julgamento final;
- D: T arquiteta, auditora e juíza;
- E opcional: mesma primitive e mesmo kernel em A e D, isolando o overhead/valor
  causal do plano T;
- F opcional: kernels nativos de cada ecossistema, medindo o sistema completo.

E responde causalidade de governança. F responde eficiência do stack. Não
confundir conclusões.

## Workloads congelados

1. FloodSurrogate;
2. regressão linear/MAE;
3. logística/BCE com working set;
4. CNN pequena com dataset e qualidade pré-definidos;
5. atenção/Transformer pequeno com sequência, máscara e critério congelados.

Usar duas modalidades: trabalho fixo e treino-até-qualidade. A equivalência é
definida antes e não relaxada depois.

## Hosts e independência

- mínimo recomendado: seis hosts físicos;
- três famílias de CPU, ao menos dois hosts por família;
- dois laboratórios ou operadores independentes;
- um coordenador não executa análise cega e coleta simultaneamente;
- reconstrução a partir de manifestos, não de máquina preparada pelo inventor.

## Energia

- métrica primária: joules totais na tomada por treinamento aceito;
- instrumento externo calibrado e com incerteza documentada;
- energia de pacote válida como métrica secundária, nunca somada a domínios
  hierárquicos sobrepostos;
- medidor controlado por máquina separada quando possível;
- notebook com bateria controlada ou host desktop para reduzir confusão;
- idle, overhead do observador e custo de compilação reportados separadamente;
- nenhuma estimativa de joules a partir de TDP, tempo ou utilização.

Referências operacionais iniciais:

- lista SPEC de analisadores aceitos: `https://www.spec.org/osg/power/docs/SPECpower-Device_List.html`;
- regras SPEC CPU 2026: `https://www.spec.org/cpu2026/docs/runrules.html`;
- regras MLCommons Training: `https://github.com/mlcommons/training_policies/blob/master/training_rules.adoc`;
- orientação Intel RAPL: `https://www.intel.com/content/www/us/en/developer/articles/technical/software-security-guidance/advisory-guidance/running-average-power-limit-energy-reporting.html`;
- política ACM/SIGMOD de reprodutibilidade: `https://reproducibility.sigmodconf.hosting.acm.org/`.

## Repetições e estatística

- sessão piloto apenas para potência e duração, excluída do confirmatório;
- mínimo operacional inicial: 24 pares válidos por host×workload, ajustado por
  análise de potência pré-registrada;
- três sessões independentes por host;
- agenda AB/BA determinística, cooldown e temperatura inicial pareada;
- análise hierárquica com host, sessão e workload explicitamente modelados;
- bootstrap pareado e teste de sinais como complementos;
- nenhuma exclusão pós-hoc; rejeições automáticas ficam preservadas;
- efeito material: razão <0,90 e IC95 inteiramente abaixo de 1 para a métrica
  pré-registrada.

## Critério confirmatório

Autoridade causal exige 9/9 mutações, publicação fail-closed e zero falso HARD
nos ataques definidos. Compressão exige equivalência e redução líquida incluindo
overhead. Vantagem energética exige medição física válida e direção consistente
entre sessões/hosts; resultado heterogêneo delimita a fronteira, não é apagado.

## Replicação adversarial

O laboratório recebe especificação, fontes, manifestos e verificador, mas cria
seus próprios scripts de recomposição. Uma equipe tenta falsificar receipts,
trocar datasets, omitir trabalho, alterar tolerâncias e explorar dependência
compartilhada entre worker e juiz. A revisão deve publicar falhas e casos
inconclusivos junto aos sucessos.
