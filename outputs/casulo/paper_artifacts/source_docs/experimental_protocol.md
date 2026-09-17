# Protocolo experimental pré-especificado

## Questões

RQ1: o executor especializado preserva o resultado numérico do treinamento de referência?

RQ2: no domínio declarado, qual é a distribuição do tempo pareado em relação a PyTorch Eager?

RQ3: quais mecanismos explicam a diferença e em que regiões ela desaparece?

RQ4: qual é a energia elétrica por treinamento equivalente quando um instrumento confiável estiver disponível?

## Ordem obrigatória

1. Congelar commit, fontes, artefato, dependências, host e política de energia.
2. Validar contrato semântico e equivalência.
3. Executar warm-ups fora das amostras.
4. Alternar a ordem candidato/baseline por agenda determinística e registrar cada par bruto.
5. Executar blocos térmicos curtos sob watchdog externo fail-closed.
6. Resfriar até o limiar pré-definido antes do bloco seguinte.
7. Calcular estatística apenas após encerrar a coleta.

## Matriz mínima definitiva

- 3 arquiteturas: MLP rasa, MLP profunda e uma operação de atenção/transformer pequena;
- pelo menos 4 tamanhos por arquitetura, escolhidos antes da medição;
- 3 baselines: PyTorch Eager, `torch.compile` do passo completo e implementação NumPy/C equivalente;
- 2 políticas de threads: 1 e um valor físico pré-definido;
- no mínimo 5 sessões independentes por host, em três dias;
- no mínimo 3 hosts x86-64 distintos; ARM é desejável, mas separado;
- sementes, ordem e exclusões registradas antes da execução.

## Métricas

- tempo de parede por treinamento completo;
- tempo de compilação separado e, adicionalmente, tempo amortizado para N execuções;
- perda, parâmetros e predições finais;
- mediana do speedup pareado e IC bootstrap de 95%;
- mediana da diferença de tempo e distribuição de log-razões;
- teste de sinais exato como verificação não paramétrica secundária;
- contagens de alocação, instruções, ciclos, cache misses e branch misses, quando disponíveis;
- joules na tomada ou RAPL validado, potência média e energia por solução equivalente.

## Regras térmicas e de segurança

Nenhum benchmark de desempenho é iniciado sem telemetria avançando, alimentação equivalente, carga de fundo baixa e cooldown estável. Odor, throttling, perda de telemetria ou limiar térmico encerram o bloco. A tentativa de 2 de agosto é classificada como `BLOCKED_BEFORE_START`; ela não contém amostra de desempenho.

## Estado desta execução de empacotamento

Nova medição de desempenho: `NOT_RUN_THERMAL_TELEMETRY_UNAVAILABLE`. O host estava sem sessão HWiNFO confiável. Reutilizam-se somente dados históricos congelados, rotulados como tal. Testes de correção leves podem ser executados com uma thread e temporários locais.

## Energia

Tempo de CPU não é energia. Enquanto não houver instrumento, os campos de joules permanecem nulos e nenhuma afirmação energética é permitida. O estudo definitivo deve preferir medidor externo calibrado; RAPL pode ser métrica auxiliar após validação contra instrumento físico.

## Critérios de conclusão

Uma afirmação de vantagem geral só poderá ser considerada após equivalência, cobertura representativa, repetição independente, comparador compilado justo, perfis causais e energia medida. Até lá, a formulação é “resultado histórico específico do workload”.
