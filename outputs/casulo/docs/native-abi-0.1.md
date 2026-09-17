# ABI nativa Casulo 0.1

## Finalidade

`casulo-native-abi/0.1` é a primeira fronteira estável entre um artefato T e
um kernel compilado. Ela não substitui o contrato Casulo: entrada, resultado,
ordem, estado e evidência continuam sendo manifestados integralmente.

O artefato portátil contém:

- `casulo_native.c`, fonte C99 regenerável a partir da CrisálidaIR;
- `casulo_native.abi.json`, descritor canônico da fronteira;
- backend Python de referência, usado como oráculo e fallback.

A DLL/SO não integra a identidade portátil. Ela é um derivado imutável,
endereçado por artefato, plataforma, compilador e hash da fonte.

## Funções exportadas

```c
uint32_t casulo_abi_version(void);
const char *casulo_artifact_id(void);

int32_t casulo_execute_f64(
    uint32_t operation,
    size_t records,
    const double *input,
    size_t column_stride,
    double *results,
    double *stabilized,
    uint8_t *states,
    uint8_t *judgements,
    uint8_t *restrictions,
    size_t *failed_record,
    uint32_t *failed_instruction
);
```

`casulo_artifact_id()` impede carregar silenciosamente uma biblioteca de outro
artefato. `casulo_abi_version()` bloqueia versões incompatíveis.

## Layout

| Buffer | Layout |
|---|---|
| entrada | colunar: `input[campo * stride + registro]` |
| resultado | `float64[registros]` |
| estado | `uint8[registros]`, zero parcial e um estável |
| julgamentos/restrições | instrução × registros |
| estabilizados | instrução × registros em `float64` |

Status zero significa sucesso. Um significa falha de `judge`; dois significa
falha de `restrict`. Status negativos representam falhas de contrato.

## Elegibilidade 0.1

- `field` não vazio composto somente por `Number`;
- saída `Number`;
- fluxo linear;
- instruções `let`, `judge`, `restrict`, `stabilize` e um único `emit`;
- expressões compostas por literais, nomes, soma, subtração, multiplicação,
  booleanos e comparações seguras.

Em execução, a versão 0.1 exige esquema exato e floats finitos. Inteiros,
campos extras, opcionais, objetos ou construções fora do subconjunto retornam
integralmente ao Python. Essa restrição conserva diferenças observáveis, como
`65` versus `65.0`.

## Reprodutibilidade

No Windows/MinGW, o link usa timestamp zero, base de imagem fixa e remoção de
símbolos não necessários. O manifesto derivado registra compilador, flags e
SHA-256 do binário. Duas compilações consecutivas fazem parte do gate do
Sprint 009.

No Linux, a mesma fonte usa C99, `-fPIC`, visibilidade oculta e biblioteca
compartilhada. A validação automatizada cobre a plataforma disponível; a matriz
Windows/Linux passa a ser gate de CI no Sprint 010.

## Fallback

Falha de elegibilidade, tipo, compilador, link, carregamento, ABI ou identidade
nunca produz resultado nativo parcial. O executor descarta essa tentativa e:

- usa o backend Python quando fallback está habilitado; ou
- bloqueia com erro quando `--native-required` foi solicitado.

Não há fallback silencioso: a API `NativeRunResult` informa `backend` e
`fallback_reason`.
