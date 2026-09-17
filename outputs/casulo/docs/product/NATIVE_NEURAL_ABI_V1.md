# Casulo Native Neural ABI v0.1

## Estado

`NF3_NATIVE_INFERENCE_ABI=PASS` não significa inferência neural. O gate prova
somente que um processo ring 3 isolado pode solicitar primitives neurais por
uma fronteira limitada, auditável e negada por padrão.

## Chamadas

| ID | Nome | Entrada | Efeito autorizado |
|---:|---|---|---|
| 7 | `MODEL_ASSERT` | descritor fixo de 64 bytes | valida schema, hash não nulo, contexto e precisão; não carrega pesos |
| 8 | `DOT_I16X4` | request RW de 24 bytes | executa produto escalar limitado e grava resultado/receipt |
| 9 | `TOKEN_EMIT` | token `u32` e evidência não nula | publica um evento de token; não decide logits nem amostragem |

O mask do processo de prova é `0x0381`: `EXIT` e exatamente as três chamadas
acima. O probe negativo recebe apenas `EXIT` e deve observar `EPERM`, um evento
de auditoria e zero primitive executada.

## Invariantes

- descritor, request e ponteiros ficam confinados às páginas do processo;
- code é RX; dados/pilha são RW+NX;
- nenhum syscall aceita caminho, rede, dispositivo, ponteiro host ou tamanho
  ilimitado;
- o kernel conta model asserts, primitives, emissões e receipt acumulado no
  ponto real do efeito;
- `TOKEN_EMIT` sem evidência é rejeitado;
- `MODEL_ASSERT` não representa que o modelo foi carregado;
- o token de prova `42` é um evento sintético de ABI e **não** é token neural.

## Para promover NF4

NF4 exige, na mesma execução QEMU, bytes de modelo content-addressed realmente
carregados, tokenizer real, cálculo de logits pelo grafo do modelo, sampling
declarado e um token cuja proveniência remonte aos pesos. Marcadores de ABI,
fixtures, caches, bridge host e binários Windows não satisfazem o gate.
