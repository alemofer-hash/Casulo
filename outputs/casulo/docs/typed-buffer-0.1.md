# Buffer tipado Casulo 0.1

## Contrato

`casulo-typed-buffer/0.1` é a representação interna do Marco 2. Ela pode mudar
como o Casulo transporta informação no caminho quente, mas não pode mudar
entrada, resultado, ordem, estado ou evidência manifestada.

## Elegibilidade

O backend Python 0.4 gera o caminho tipado quando:

- a operação recebe um `field` composto somente por `Number`;
- a saída é `Number`;
- o corpo é retilíneo;
- as instruções pertencem a `let`, `judge`, `restrict`, `stabilize` e `emit`;
- existe um único `emit`, na última posição.

Em execução, todos os registros ainda precisam possuir o esquema exato e usar
uma representação numérica homogênea: somente `float64` ou somente inteiros
assinados de 64 bits. Caso contrário, o lote inteiro retorna ao kernel de
objetos.

## Layout

| Informação | Representação |
|---|---|
| campos numéricos | uma `array('d')` ou `array('q')` por campo |
| registro → entrada única | `array('I')` |
| ocorrência reutilizada | `bytearray` |
| estado estável | `bytearray` |
| julgamentos e restrições | `bytearray` lateral por instrução |
| valores estabilizados | buffer lateral indexado pela entrada única |
| envelopes | materializados somente depois do kernel |

As chaves continuam seguindo `casulo-structural-key/0.1`. O buffer não reduz a
proteção contra colisões nem mistura `+0.0` com `-0.0`.

## Fallback

O caminho tipado retorna `None` internamente quando encontra uma forma
incompatível. `execute_batch` então executa o kernel de objetos integralmente.
Nenhum resultado parcial, cache persistente ou evidência incompleta atravessa
essa fronteira.

## Telemetria

O envelope de lote registra:

```json
{
  "buffer_protocol": "casulo-typed-buffer/0.1",
  "representation": "columnar-typed",
  "evidence_layout": "lateral",
  "hot_path": {
    "records": 2000,
    "unique_records": 1000,
    "column_type": "float64",
    "column_bytes": 32000,
    "reference_intermediate_mappings_avoided": 6000,
    "reference_intermediate_lists_avoided": 5000,
    "reference_field_writes_avoided": 8000
  }
}
```

Os contadores `reference_*` são diferenças estruturais exatas contra o kernel
de objetos gerado pelo mesmo artefato. Medidas de pico e blocos retidos são
obtidas separadamente pela Borboleta com `tracemalloc`.

## Limites

- os buffers ainda são percorridos por bytecode Python;
- não existe SIMD;
- tipos numéricos mistos usam fallback;
- objetos e arrays aninhados ainda não entram no caminho colunar;
- bytes de buffer não equivalem a bytes totais movimentados pelo processador;
- tempo de CPU não equivale a joules.
