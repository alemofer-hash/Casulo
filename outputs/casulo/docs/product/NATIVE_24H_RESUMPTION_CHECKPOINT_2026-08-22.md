# Checkpoint de retomada — objetivo central Native em 24 horas

Capturado em: `2026-08-22T11:06:59-03:00`  
Estado: `PAUSED_AWAITING_24H_EXECUTION_SIGNAL`  
Escopo deste registro: preservar o ponto exato da interrupcao e congelar um
plano; nenhum gate NP7+ foi executado por este checkpoint.

## Baseline factual preservado

- repositorio: `C:\Users\guimo\Documents\Codex\2026-07-28\ex\outputs\casulo`;
- branch: `product/semantic-multiverse`;
- commit-base: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree historico preservado: 22 arquivos versionados modificados e uma
  arvore nao rastreada muito grande; a enumeracao corrente encontrou 75.883
  arquivos, com avisos de caminhos longos, portanto esse numero nao e tratado
  como identidade completa do worktree;
- espaco livre observado: `59,39 GiB` no volume C;
- nenhuma limpeza, reset, checkout, stash ou remocao foi realizada;
- Cloud permanece `RELEASE_LOCKED`;
- rede guest permanece OFF;
- nenhum USB ou block device fisico foi acessado;
- nenhuma campanha cientifica ou energetica foi iniciada.

## Ultimo gate comprovado

Estado autoritativo:
`NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING`.

O NP6 executou no Casulo Native, para um token autentico do modelo adotado:

- embedding Q6_K;
- RMSNorm;
- projecoes Q/K/V;
- Q/K norm;
- RoPE;
- atencao GQA e softmax;
- projecao de atencao e residual;
- RMSNorm;
- SwiGLU;
- down projection e residual.

Evidencia delimitada:

- 19/19 estagios comparados com oraculo independente;
- 100.925.440 MACs contabilizados para o bloco;
- 63.866.880 bytes de pesos consumidos pelos matvecs;
- 3/3 boots WHPX reproduziram o mesmo hash de saida;
- imagem autoritativa:
  `release/casulo-native-neural-port-np6-attempt-4.img`;
- bytes da imagem: `3.211.264`;
- SHA-256 da imagem:
  `65a9b4360ef56355aececd16731ed33d4f508b82d6aff2043d75abc05624fef0`;
- SHA-256 do manifest:
  `530ace62f5112d05ef4abd1958ebc86711cd74acc058a2a4a042bf3d9347fd23`.

## O que ainda nao aconteceu

- blocos Transformer 1 a 35 nao foram executados no guest;
- output RMSNorm e logits nao foram calculados;
- sampling nao foi executado;
- nenhum token de saida foi derivado dos pesos no Native;
- nao existe ainda conversa neural completa sem Windows/Linux;
- nao existe ainda driver Native fisico para armazenamento do GGUF;
- a rota QEMU usa `fw_cfg`, que nao e driver final de hardware;
- audio, ASR/TTS e GPU Intel Native nao estao prontos;
- o metodo FROZEN/WARM/HOT reduz working set, contexto e trabalho evitavel,
  mas nao foi provado como substituto dos 36 blocos do Qwen;
- nao ha evidencia de equivalencia com modelos frontier ou de que um Qwen3-4B
  tenha a mesma capacidade geral dos maiores modelos atuais.

## Proximo gate exato

`NP7_ALL_36_BLOCKS_AND_LOGITS`:

1. generalizar RoPE e KV cache bounded;
2. executar os 36 blocos com watchdog e cancelamento;
3. executar RMSNorm final;
4. calcular logits de forma bounded;
5. confrontar logits com oraculo independente;
6. impedir sampling se qualquer etapa divergir.

## Definicao de vitoria para a janela de 24 horas

A vitoria honesta da janela nao e "SO completo" nem "modelo frontier". E um
vertical slice causal denominado:

`CASULO_NATIVE_BOOT_TO_CREATION_PROOF`

Ele exige, no minimo:

1. boot do kernel Casulo sem Linux no guest;
2. modelo Qwen3-4B local verificado consumido pelo runtime Native;
3. pelo menos um ciclo mult-token real, com streaming e cancelamento;
4. entrada humana em linguagem comum;
5. Intent/RequirementGraph e politica T consumidos antes da criacao;
6. uma criacao simples e inedita compilada/executada com receipt real;
7. superficie Stark + Jobs mostrando apenas progresso verdadeiro;
8. falha recuperavel sem traceback;
9. imagem, manifest, hashes e comando unico para reproducao;
10. teste em QEMU antes de qualquer tentativa fisica.

O boot fisico por pendrive e um gate separado. Ele exige identificar exatamente
a midia e autorizacao destrutiva literal depois que a imagem passar em QEMU.
O sinal para iniciar as 24 horas nao e, por si so, autorizacao para gravar USB.

## Plano congelado de 24 horas

### H0-H1 — freeze, doctor e protocolo

- verificar hashes NP6, modelo, QEMU e toolchain;
- congelar prompt, tokenizer, sampling, limites de memoria e criterios de
  equivalencia;
- medir somente o necessario para decidir arquitetura; nenhuma campanha
  cientifica;
- criar rollback e checkpoints append-only.

Gate: baseline reproduzivel e zero mutacao no modelo/release anterior.

### H1-H5 — NP7: decoder completo correto

- generalizar o executor de bloco para indices 0..35;
- implementar KV bounded e RoPE geral;
- executar output norm e projecao de logits sem materializar estado
  desnecessario;
- criar oraculo independente por bloco/digest/top-k;
- rejeitar truncamento, tensor errado, cancelamento tardio e mismatch.

Gate: 36/36 blocos, logits e receipts exatos; sampling ainda bloqueado.

### H5-H7 — NP8: primeiro token real

- congelar sampling debug deterministico;
- produzir o primeiro token somente a partir dos logits validados;
- selar model hash, prompt hash, token IDs, logits digest, token escolhido,
  blocos completos e bytes lidos;
- reproduzir em tres boots.

Gate: primeiro token derivado dos pesos, sem fake, replay ou API externa.

### H7-H11 — NP9: loop mult-token util

- decodificacao incremental com KV cache;
- streaming token a token;
- cancelamento cooperativo entre bloco/token;
- scheduler PRESENCE acima de BACKGROUND;
- token tardio nunca publicado;
- caminho SIMD/AVX2 bounded somente depois de a rota escalar ser correta.

Gate: resposta curta coerente em pt-BR, com contadores e sem congelar input.

### H11-H14 — miniaturizacao que nao mente

- ligar Semantic Multiverse ao ContextAssembler;
- manter HOT apenas os universos suficientes;
- T decidir contexto, working set, budgets e invocacao neural;
- comparar ALL_HOT versus sparse apenas como micro-medida de UX/recursos;
- nunca pular camada neural sem equivalencia demonstrada.

Gate: menos contexto/estado/chamadas quando dispensaveis, sem perda HARD ou
claim de compressao universal.

### H14-H18 — boot-to-creation

- conectar conversa livre a IntentTwin/RequirementGraph;
- nao perguntar jargao tecnico: transformar lacunas em perguntas sobre
  finalidade, comportamento e limites observaveis;
- gerar T pelo pipeline geral, compilar, simular e executar uma criacao pequena;
- materializar em memoria ou sistema virtual delimitado;
- receipts provam cada transicao.

Gate: uma ideia nova em linguagem leiga vira artifact funcional e auditavel.

### H18-H21 — Stark + Jobs Native

- ligar streaming e Creation Field ao PresentationProjector existente;
- resposta aparecer gradualmente, nunca como bloco repentino;
- estados de espera, erro, reparo e conclusao derivados de eventos reais;
- teclado como caminho primario desta prova; voz permanece fora do gate se o
  driver de audio Native nao estiver pronto.

Gate: sessao QEMU utilizavel, interrompivel e sem painel tecnico no caminho
principal.

### H21-H23 — reseal e ensaio humano local

- regressao focal Native/T/produto;
- tres boots;
- corrupcao, cancelamento, falta de modelo e falha visual;
- reconstruir imagem, manifest, SBOM, SHA256SUMS e launcher;
- doctor read-only e runbook de cinco minutos.

Gate: pacote reproduzivel `DEVELOPMENT_NOT_COMMERCIAL`.

### H23-H24 — decisao fisica

- se e somente se o vertical slice passar: preparar imagem fisica e inventario
  read-only de midias;
- solicitar autorizacao literal para um unico pendrive identificado;
- gravar, verificar hash e tentar boot sem tocar no NVMe interno;
- se drivers de input/model source bloquearem interacao fisica, preservar o
  boot e declarar exatamente a fronteira; nao fingir uma experiencia completa.

Gate maximo possivel: `READY_FOR_GUILHERME_NATIVE_BOOT_TO_CREATION_PROOF`.

## Regras de desvio

- mismatch numerico: corrigir antes de otimizar;
- executor completo lento: perfilar e vetorizar primitives, nao omitir blocos;
- GPU indisponivel: permanecer CPU; nao prometer driver Intel em 24 horas;
- voz indisponivel: texto continua valido para o vertical slice, mas o estado
  final nao pode ser chamado voice-first completo;
- falta de driver fisico: concluir a prova em QEMU e encerrar com bloqueio
  fisico preciso;
- temperatura/odor/throttling: interromper carga e preservar artifacts;
- nenhuma rota pode usar Windows `llama.cpp` e ao mesmo tempo alegar inferencia
  Native.

## Claims que este plano nao autoriza

- equivalencia com GPT frontier;
- eliminacao de datacenters;
- dominio geral irrestrito;
- controle de GPU/TPU sem drivers;
- Casulo OS completo ou pronto para uso diario;
- compressao fisica/energetica sem medicao valida;
- experiencia final aprovada em nome de Guilherme.

## Proximo ato permitido

Esperar o sinal literal de Guilherme. Depois do sinal, iniciar em H0 e manter
checkpoints duraveis sem pedir `prossiga` entre gates corrigiveis. Escrita em
pendrive continua exigindo consentimento destrutivo separado e target exato.
