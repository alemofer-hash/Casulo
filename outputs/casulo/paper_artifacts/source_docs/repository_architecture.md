# Arquitetura auditada do Casulo/Linguagem T

## Escopo e identidade

Este documento descreve o repositório no commit `df12e916c90d9bd2b966326275dc191573f38abd`. O autor informado para o trabalho científico é **Guilherme Moura Fernandes**. Nenhuma afiliação, titulação, ORCID ou endereço de correio eletrônico foi inferido.

## Caminho geral da linguagem

1. `EggLexer` (`src/casulo/t/lexer.py`) transforma a fonte em tokens e preserva a estrutura de indentação.
2. `EggParser` (`src/casulo/t/parser.py`) constrói a árvore sintática.
3. `LarvaAnalyzer` (`src/casulo/t/analyzer.py`) resolve símbolos, tipos e a obrigação de emissão em todos os caminhos.
4. `CrisalidaLowerer` (`src/casulo/t/ir.py`) produz uma representação intermediária versionada.
5. `MetamorfoseGraphBuilder` (`src/casulo/t/graph.py`) explicita dependências de execução.
6. `ArtifactBuilder` (`src/casulo/t/artifact.py`) gera fontes Python/C99 e artefatos endereçados por conteúdo, com JSON canônico e SHA-256.
7. Os backends Python e nativo executam o artefato. O backend nativo usa C99, arena reutilizável, cache imutável e, quando aplicável, SIMD.

## Caminho tensorial e álgebra linear

- `LarvaTensor` carrega `dtype`, forma, layout e informações de alias.
- O IR tensorial torna explícitos buffers e dependências.
- O planejador de memória calcula tempos de vida e reutilização segura.
- A autodiferenciação usa regras versionadas e lowering reverso explícito.
- `EggGemmContract`, `LarvaTrafficProfile` e `CrisalidaGemmPlan` separam contrato, diagnóstico de tráfego e decisão de execução.
- O backend CPU contém arena, regiões de fusão e GEMM de trabalhadores fixos ou adaptativos, com caminho C99/OpenBLAS e fallback declarado.

## Caminho real do experimento de treinamento

O experimento de treinamento atual **não atravessa integralmente** o frontend geral descrito acima. `parse_training_spec`, em `src/casulo/t/training.py`, implementa um parser especializado para a construção `learn`. O artefato é produzido por `build_training_artifact` e `_render_training_c`, que gera C especializado para uma MLP de uma camada oculta.

O domínio aceito no estado auditado é deliberadamente estreito:

- 1 a 64 atributos de entrada;
- 1 a 256 unidades ocultas;
- exatamente uma saída;
- ativação ReLU ou tanh;
- perda MSE e otimizador SGD;
- lote completo e `float64`.

O C gerado executa passagem direta, retropropagação e atualização SGD em laços especializados. Gradientes são alocados uma vez por chamada de treinamento; o paralelismo OpenMP, quando habilitado, é limitado a até quatro trabalhadores.

## Comparadores

O comparador primário é PyTorch Eager via Python, com `torch.float64`, `torch.optim.SGD` e autograd. O comparador secundário é PyTorch/Inductor. Na implementação auditada do secundário, apenas o módulo de passagem direta é entregue a `torch.compile`; o laço de épocas, a retropropagação e o otimizador não formam um único grafo compilado. A compilação é aquecida e excluída do tempo medido.

## Consequência científica

Os resultados históricos demonstram que um executor C especializado pode reduzir substancialmente a sobrecarga do stack Python/autograd nesse problema pequeno. Eles não isolam a sintaxe da Linguagem T como causa, não provam que o frontend geral já compila o treinamento e não demonstram superioridade universal sobre PyTorch ou Inductor.

## Limitações estruturais observadas

- cobertura de treinamento limitada a uma MLP rasa;
- álgebra linear centrada em `matmul` rank-2;
- ausência de GPU/TPU;
- ausência de packing persistente e de fusão geral GEMM+epílogo;
- energia elétrica não medida;
- comparação histórica em um único host e uma sessão por comparador;
- ausência, neste pacote, de repetição independente com telemetria térmica válida.
