# Sprint 017 — executor NumPy e paridade PyTorch

## Entrega

- protocolo `casulo-numpy-executor/0.1`;
- execução pública do forward e backward;
- manifestação de saídas e gradientes;
- hashes de grafo, entradas e valores;
- adaptador `casulo-pytorch-adapter/0.1`;
- comparação de todos os intermediários;
- comparação da loss e dos gradientes;
- tolerâncias distintas para `float32` e `float64`;
- vereditos `PASS`, `FAIL` e `INCONCLUSIVE`;
- indisponibilidade do PyTorch preservada como inconclusiva;
- comandos `t numpy-execute` e `t pytorch-parity`;
- corpus pequeno `float64` e médio `float32`;
- casos negativos de shape, dtype, não finitos e erro numérico.

## Invariantes

- os dois backends recebem o mesmo hash de entrada;
- os dois backends executam o mesmo hash de grafo;
- nenhum intermediário é omitido da comparação;
- shape divergente falha antes da tolerância;
- dtype divergente falha antes da tolerância;
- `NaN` ou infinito falha explicitamente;
- PyTorch ausente não produz aprovação;
- relatório não mede nem sugere velocidade;
- tempo e energia permanecem `null`.

## Resultado

No exemplo linear MSE `float64`:

- sete verificações;
- quatro valores forward;
- três gradientes;
- erro absoluto máximo `0`;
- veredito `PASS`.

Identidade do grafo:

`4e774833fb42d67463b5491aba7c8f507e0cbbe3011c4316c7246f4f5626c61b`

Identidade das entradas:

`77a53f66d2c0734224b9e6452ac97960d0e421f93009bd14bfb90365e5265270`

SHA-256 do relatório reproduzido duas vezes:

`EB64C67E12278CE4C14C9195A7A6396A2F9ED60EDA8B6FFC29857A516D2EE5F0`

O MLP `float32` 64×16→32→8 também passou dentro da tolerância registrada.

## Próximo passo

O Sprint 018 iniciará o backend CPU tensorial:

1. formar regiões de fusão semântica;
2. calcular tempo de vida de buffers;
3. reutilizar arena sob orçamento explícito;
4. gerar um kernel CPU de referência para forward e backward;
5. preservar o executor NumPy e PyTorch como autoridades de correção;
6. medir equivalência antes de medir velocidade;
7. manter qualquer benchmark exploratório sem claim público.

## Correção operacional 0.18.0-alpha.2

O runtime deixou de depender do Python ou do terminal que por acaso resolvesse
o comando `t`. O diagnóstico `t pytorch-doctor` executa CPU e autograd; a opção
`--compile` localiza o Visual Studio Build Tools, ativa `vcvars64.bat`, aplica
uma política de saída UTF-8/inglesa e executa um grafo Inductor real.

No Windows de desenvolvimento, o teste foi iniciado sem `cl.exe` no `PATH` e
terminou com:

- PyTorch `2.12.1+cpu`;
- NumPy `2.3.5`;
- eager/autograd `PASS`;
- Inductor `PASS`;
- MSVC `14.44.35207` descoberto automaticamente;
- timing e energia `null`, pois o diagnóstico não é benchmark.
