# Cadeia semântica e hipótese causal

## Invariantes de equivalência

Antes de qualquer afirmação de desempenho, os dois caminhos devem compartilhar: dados e divisão de treino/validação; inicialização; arquitetura; precisão; função de ativação; perda; regra SGD; taxa de aprendizado; número de épocas; lote; número de threads; política de compilação e aquecimento declaradas.

A execução só é considerada equivalente quando parâmetros finais, predições e perda satisfazem tolerâncias registradas. Resultado rápido sem equivalência é rejeitado.

## Cadeia causal plausível

`contrato de treinamento restrito` → `formas e laços conhecidos antes da execução` → `geração de uma unidade C especializada` → `menos despacho Python e menos objetos/autograd dinâmicos por época` → `buffers e laços previsíveis` → `menor tempo no workload auditado`.

Esta cadeia é uma hipótese causal sustentada por inspeção de código. Para atribuição experimental, cada elo precisa de ablação:

1. mesmo algoritmo em Python/NumPy sem autograd;
2. C especializado sem arena/reuso;
3. C especializado com/sem OpenMP;
4. C especializado com/sem otimizações do compilador;
5. PyTorch funcional/compilado com `torch.compile` abrangendo passo de treino completo;
6. dimensões e lotes variados, incluindo regiões em que kernels BLAS dominam;
7. perfis de CPU, alocações, cache misses e contadores de hardware.

## O que a evidência histórica sustenta

- equivalência numérica observada no caso FloodSurrogate;
- menor tempo pareado para o candidato nas 21 pares de cada sessão histórica;
- magnitude grande nesse problema e ambiente específicos;
- custo de compilação do caminho Inductor explicitamente separado.

## O que ela não sustenta

- “T é seis vezes mais rápida” como lei geral;
- equivalência com todos os modelos que PyTorch aceita;
- eficiência energética, pois joules não foram medidos;
- substituição de centenas de núcleos;
- vantagem em GPU, modelos profundos, convoluções, atenção ou treinamento distribuído;
- atribuição exclusiva do ganho à sintaxe ou ao escalonador adaptativo.

## Experimentos de falsificação

A hipótese é enfraquecida se: a equivalência falhar; o ganho desaparecer contra um baseline compilado de passo completo; a vantagem não sobreviver a repetições independentes e máquinas distintas; perfis mostrarem que a diferença vem de trabalho matemático omitido; ou energia por solução equivalente não melhorar quando medida fisicamente.
