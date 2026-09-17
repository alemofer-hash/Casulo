# Plano de execução Qwen3 no Casulo Native

## Encerramento NP10 — 2026-08-22

Estado atual: `CASULO_NATIVE_BOOT_TO_CREATION_PROOF`. NP7–NP10 foram
implementados; três boots positivos e um boot cancelado passaram com a imagem
SHA-256 `25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534`.
O defeito RoPE mult-token de NP9 foi preservado e corrigido conforme
`NP9_DECODER_FIDELITY_ERRATA.md`. O restante deste documento conserva o plano
incremental que conduziu ao resultado e não deve ser lido como estado pendente.

Estado: NP6 aprovado; contrato técnico para `NP7+`; um bloco completo não é uma inferência de decoder completa.

## Decisão arquitetural

O GGUF owner será tratado como um objeto content-addressed read-only. Em VM, o
host pode apresentar somente o arquivo regular previamente verificado como
mídia virtual somente leitura. O guest deve ler setores/páginas sob capability,
sem montar discos do host, sem aceitar caminhos arbitrários e sem rede.

Não serão aceitos:

- copiar o GGUF inteiro para o system pack;
- embutir outra cópia dos pesos na imagem do kernel;
- anexar `PhysicalDrive`, USB real ou qualquer block device físico;
- confiar em nome de arquivo sem tamanho e SHA-256;
- declarar sucesso ao apenas abrir o modelo.

## Pipeline do primeiro token

```text
modelo read-only verificado
→ GGUF v3 bounded parser
→ tokenizer/chat template verificados
→ token IDs
→ embedding Q6_K
→ 36 × (RMSNorm → atenção GQA/RoPE/KV → residual
        → RMSNorm → SwiGLU FFN → residual)
→ output RMSNorm
→ output projection
→ sampling policy
→ token receipt
→ Guide Presence
```

## Gates incrementais

### NP4 — I/O paginado do modelo

- **PASS em 2026-08-20**;
- transporte QEMU `fw_cfg` DMA somente leitura sobre o arquivo regular owner;
- modelo completo permaneceu fora do heap;
- cache limitado e contabilizado;
- identity `{bytes, sha256, gguf_version, architecture}` verificada pelo host e
  estrutura reconfirmada pelo guest;
- item ausente, truncamento, corrupção local e offset fora dos limites foram
  rejeitados.

### NP5 — tokenização e embedding

- **PASS bounded em 2026-08-21**;
- vocabulário e merges foram consumidos do próprio GGUF;
- três entradas ASCII/latinas, incluindo pt-BR, coincidiram com o runtime owner;
- uma linha de `token_embd.weight` Q6_K foi dequantizada integralmente;
- special tokens, scripts não latinos e template permanecem fail-closed;
- ainda sem alegação de compatibilidade total ou token de saída.

O transporte NP4 é próprio para qualificação em QEMU. O caminho em hardware
físico exigirá um driver read-only equivalente; `fw_cfg` não é apresentado como
driver final do Casulo OS.

### NP6 — um bloco Transformer

- **PASS em 2026-08-21**;
- um token autêntico executou integralmente o bloco zero no guest;
- 19/19 estágios intermediários coincidiram com o oráculo independente;
- o host executou dois tokens e 38/38 estágios, incluindo contexto causal 2;
- output scalar Rust idêntico em 3/3 boots WHPX;
- nenhum bloco posterior, logit, sampling ou output token foi executado.

### NP7 — 36 blocos e logits

- arena de ativações explicitamente dimensionada;
- KV cache com contexto de prova pequeno e contrato de crescimento;
- watchdog/cancelamento em cada bloco;
- logits comparados antes do sampling;
- nenhuma otimização que altere o oráculo antes de correção integral.

### NP8 — primeiro token derivado dos pesos

- prompt e sampling congelados;
- token produzido somente depois de todos os 36 blocos;
- receipt inclui modelo, tokenizer, política, prompt hash, logits digest,
  token ID e tempos de fase;
- três boots, mesma seed debug e mesmo token;
- execução estocástica fica para gate separado.

### NP9 — streaming, cancelamento e Presence

- múltiplos tokens;
- cancelamento invalida conclusão tardia;
- progresso nasce de eventos de bloco/token reais;
- UI continua responsiva;
- falha neural não derruba memória, criação ou renderer.

## Fronteiras estrangeiras permitidas

O formato GGUF, a arquitetura Qwen3 e os pesos permanecem componentes
bootstrap. Primitives SIMD e intrinsics de baixo nível podem ser estrangeiras
se manifestadas e verificadas. Política, capabilities, ciclo de vida,
proveniência, cancelamento, publicação e integração com T permanecem sob
autoridade Casulo.

## Orçamento inicial

- modelo read-only: 2.497.280.256 bytes fora do heap;
- ativação máxima por vetor FFN F32: 38.912 bytes;
- logits F32 para 151.936 tokens: 607.744 bytes;
- KV por token em F32: `36 × 2 × 8 × 128 × 4 = 294.912 bytes`;
- KV por token em F16: 147.456 bytes;
- contexto completo de 40.960 tokens não cabe no envelope atual;
- o gate de primeiro token usa contexto mínimo congelado e não falsifica suporte
  ao contexto máximo do arquivo.

NP6 introduziu arena explícita de 259.328 bytes e prefetch DMA de 256 KiB,
ambos dentro do heap/perfil de memória atual. NP7 deve dimensionar o KV cache
por contexto e não pode inferir suporte aos 40.960 tokens do metadata.

## Verificação independente

Cada NP deve produzir:

- input e output hashes;
- bytes realmente lidos;
- tensor/offset/tipo;
- contadores de blocos e operações;
- resultado contra oráculo;
- motivos de rejeição;
- imagem/modelo antes e depois;
- ausência de rede e dispositivos físicos.

Um marker de serial isolado não basta. O verificador deve recompor os receipts
e rejeitar execução incompleta.
