# ARC-8 — Fronteira matemática do Casulo

Data: 2026-08-18  
Estado: `IMPLEMENTADO_TESTADO`  
Claim class: `BOUNDED_PRODUCT_KERNEL_ONLY`

## Resposta técnica à tese

T pode reduzir trabalho matemático quando altera a representação, especializa
um kernel e preserva exatamente sua semântica. T não substitui automaticamente
pesos, multiplicações de matrizes ou kernels vetorizados apenas por expressar a
mesma conta em outra sintaxe.

O primeiro slice produtivo foi o cosseno signed-hash de 64 posições usado pela
`LivingMemory`. A referência materializava 64 posições, quase todas zero. O
candidato guarda somente coordenadas não nulas e executa a mesma fórmula.

## Fronteiras reais

| Fronteira | Implementação atual | Ação ARC-8 | Claim |
|---|---|---|---|
| inferência owner | Qwen3-4B GGUF, llama.cpp/ggml | manifestar como primitive estrangeira | T não substitui esta álgebra |
| ASR owner | Whisper, whisper.cpp/ggml | manifestar como primitive estrangeira | T não substitui esta álgebra |
| similaridade da memória | Python first-party, vetor signed-hash denso | especialização esparsa governada por T | válido somente para este kernel |
| avaliador Einstein | Python first-party, geometria 4D local delimitada | fora do hot path genérico | não é solver global |
| tensor stack histórico | JSON Tensor IR + C99/OpenMP | preservar como pesquisa fora do owner | não conta como soberania owner |

## Autoridade T real

`private/casulo-owner/t-v2/math-boundary-policy.t` recebe fatos produzidos por
medição e verificação. O candidato só é adotado se todos forem verdadeiros:

1. implementação e fallback estão declarados;
2. equivalência semântica passou;
3. candidato foi medido;
4. tráfego lógico diminuiu;
5. razão candidato/referência ficou abaixo do limiar congelado `0,95`;
6. execução não foi cancelada.

O receipt T é anterior à seleção. O resultado é consumido pelo launcher owner.
Mutar o `return ok` da política para uma negação muda o kernel executado. Se T
ou o TCAP estiver indisponível, o sistema mantém a referência densa; a camada
Python nunca reconstrói uma aprovação afirmativa.

## Resultado local delimitado

Evidência:
`product-demos/human-proof/arc-math-boundary-2026-08-18-attempt1`.

- equivalência: `10/10`, diferença absoluta máxima `0.0`, tolerância `1e-15`;
- posições lógicas por corpus de qualificação: `86` esparsas contra `1280`
  densas;
- perfil curto: mediana `65.404 ms` candidata contra `85.6974 ms` referência;
- razão candidata/referência: `0.763197`;
- decisão: `T_ADOPTED_SPECIALIZED`;
- manifest SHA-256:
  `c2da7ca035a83d2bc8e893e5b6401a346485597621843a42cc238e4c8ad6e776`.

Os tempos agregam 4.000 pares por rodada e servem apenas para a decisão local
de produto. Não são throughput de diálogo, energia, treino, FLOPs ou benchmark
científico. O valor pode mudar em outro host; nesse caso T deve negar a adoção
e preservar o baseline.

## Integração owner

O launcher Semantic Multiverse qualifica a política antes de construir a
`T85ContinuityService`, injeta o kernel selecionado na `LivingMemory` e expõe o
ID/hash da decisão em `:memoria`. A fórmula de ranking, pesos lexical/vetorial,
proveniência e comportamento de recall não mudaram.

## Claims proibidos

- “T substituiu as matrizes do Qwen.”
- “Casulo venceu álgebra linear geral.”
- “A pilha tensorial histórica já executa o motor owner.”
- “O resultado prova vantagem energética, científica ou universal.”

## Próximo limite

O gargalo dominante continua sendo inferência neural em llama.cpp/ggml. O
próximo ganho deve vir de menor trabalho solicitado ao modelo, cache de estado
seguro, contexto mínimo e UX streaming — ou de uma especialização futura que
prove equivalência no kernel específico. Nenhum ganho pequeno autoriza uma
reescrita de kernels maduros por identidade de linguagem.
