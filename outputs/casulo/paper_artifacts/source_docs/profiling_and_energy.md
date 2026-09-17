# Perfis, mecanismos e energia

## Perfis disponíveis

Os artefatos do Sprint 024 são perfis **estruturais**, não amostras de runtime. Para grafos `tall`, `wide` e `deep`, 98,60%, 99,43% e 99,24% dos FLOPs conhecidos, respectivamente, pertencem a GEMM. A arena reaproveita aproximadamente 26,9%, 26,8% e 30,7% dos bytes calculados. Há somente duas regiões fundidas por grafo.

Esses números priorizam hipóteses: escolha de provedor/threads por GEMM; prevenção de oversubscription; destination passing; fusões adicionais; provedores alternativos; e autotuning selado. Eles **não provam** que GEMM domina o tempo de parede. A ablação bloqueada de 2 de agosto era justamente uma tentativa de falsificar essa inferência, mas nenhum bloco de desempenho começou.

## Perfis ainda necessários

- tempo por operador e por região fundida;
- stacks de CPU e amostragem do comparador Python;
- instruções, ciclos, IPC, cache misses e branch misses;
- bytes alocados, número de alocações e picos de memória;
- frequência efetiva, temperatura e throttling sincronizados;
- contagem de chamadas a kernels BLAS e tamanho de cada GEMM;
- passo completo do Inductor exportado e inspecionado.

## Energia

Todos os relatórios históricos de treinamento registram `electrical_energy_measured=false` e `joules=null`. Portanto:

- não existe resultado de eficiência energética no pacote;
- potência estimada por software não deve substituir um medidor físico sem calibração;
- tempo de CPU, uso percentual e temperatura não são proxies suficientes para joules;
- a futura unidade de comparação é joules por treinamento semanticamente equivalente, com a mesma fronteira de sistema.

## Protocolo futuro de energia

Usar medidor externo na tomada com resolução e calibração documentadas; registrar energia ociosa numa janela equivalente; medir wall time e joules sincronizados; alternar ordem; repetir sessões; reportar energia bruta e energia incremental sobre idle. RAPL pode ser incluído como série auxiliar e validado contra o instrumento externo.
