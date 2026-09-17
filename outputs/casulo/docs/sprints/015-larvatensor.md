# Sprint 015 — LarvaTensor

## Entrega

- protocolo `casulo-tensor-type/0.1`;
- shapes estáticos e simbólicos;
- dtype, device, layout, ownership e aliasing;
- registro versionado de operadores;
- ABI declarativa de extensões;
- inferência conservativa de broadcasting, `matmul`, reduções e views;
- representação `casulo-tensor-ir/0.1`;
- nomes SSA e referências verificadas;
- planejamento estático de memória por tempo de vida;
- comando `t tensor-compile`;
- exemplo de forward de MLP;
- corpus positivo e negativo automatizado.

## Invariantes

- nenhuma dimensão inválida chega ao backend;
- nenhum dtype é promovido silenciosamente;
- nenhum device é transferido implicitamente;
- toda view conserva o grupo de alias da origem;
- entrada borrowed não pode ser mutada;
- ABI divergente é recusada;
- dimensão simbólica não produz estimativa fictícia de memória;
- lowering não executa código de extensão.

## Resultado

O exemplo `mlp-forward.tensor.json` é baixado deterministicamente para três
instruções tensoriais. Com shapes estáticos, o plano calcula:

- 139.520 bytes de entradas;
- 528.384 bytes de resultados alocados;
- 663.808 bytes de pico vivo.

Esses números descrevem o grafo, não são uma medição de RSS e não constituem
alegação de ganho de velocidade.

## Próximo passo

O Sprint 016 introduzirá Metamorfose Autograd 0.1:

1. grafo forward/backward explícito;
2. regras de derivada versionadas;
3. verificação numérica por diferenças finitas;
4. acumulação determinística de gradientes;
5. primeiro executor de referência NumPy;
6. adaptador de paridade com PyTorch, ainda sem alegação de velocidade.
