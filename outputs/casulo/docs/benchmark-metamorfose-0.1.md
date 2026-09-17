# Protocolo de benchmark da Metamorfose 0.1

**Identificador:** `metamorfose-benchmark/0.1`
**Origem:** Teloscorp / Casulo

## Pergunta

O kernel de lote reduz o custo de executar a mesma operação T sobre vários
registros sem alterar a saída?

## Comparação

O benchmark mede o mesmo módulo gerado em dois modos:

- `python_scalar_loop`: uma chamada escalar por registro;
- `metamorfose_fused_batch`: um laço gerado que mantém a operação dentro do
  mesmo frame de execução.

O cache fica desativado nos dois modos. Antes da cronometragem, o sistema
calcula o SHA-256 das saídas completas e exige equivalência.

## Métricas

- tempo de parede com `perf_counter_ns`;
- tempo de processo com `process_time_ns`;
- nanossegundos por registro;
- registros por segundo;
- fator de aceleração;
- razão de trabalho de CPU.

O tempo de CPU é um proxy de trabalho computacional. Ele não é energia
elétrica. O campo `electrical_energy_joules` permanece `null` até existir
medição por RAPL, tomada instrumentada ou equipamento equivalente.

## Controle de ruído

- aquecimento antes das amostras;
- ordem escalar/lote alternada;
- coleta de lixo suspensa durante a região medida;
- múltiplas amostras;
- mediana em vez de melhor resultado.

## Comando de referência

```powershell
t benchmark artefato `
  --input examples/t/hydrocell_batch.json `
  --repeat 1000 `
  --samples 7 `
  --iterations 10 `
  --output benchmark.json
```

## Baseline local de 29 de julho de 2026

Ambiente registrado pelo relatório:

```text
CPython 3.13.2
Windows 11
AMD64
Intel64 Family 6 Model 154
3.000 registros por amostra
10 iterações
7 amostras
```

Medianas observadas:

| Modo | Tempo de parede | Throughput | Tempo de CPU |
|---|---:|---:|---:|
| escalar | 1,540 s | 19.475 registros/s | 1,531 s |
| lote fundido | 1,376 s | 21.804 registros/s | 1,344 s |

Nesta execução:

```text
wall_speedup = 1,1196x
throughput_ratio = 1,1196x
cpu_work_ratio = 1,1395x
```

Isso é um baseline local, não uma promessa universal. Arquitetura, temperatura,
plano de energia, versão do Python, tamanho do lote e forma da operação podem
alterar o resultado.

O relatório bruto está versionado em
`benchmarks/results/2026-07-29-water-balance-python313.json`.

## Próximo experimento energético

Para transformar o proxy em energia:

1. fixar modo de energia e temperatura inicial;
2. usar Intel RAPL quando exposto pelo sistema ou medidor externo;
3. medir joules antes e depois da região;
4. subtrair baseline ocioso;
5. publicar joules por milhão de registros;
6. repetir com intervalos de confiança.
