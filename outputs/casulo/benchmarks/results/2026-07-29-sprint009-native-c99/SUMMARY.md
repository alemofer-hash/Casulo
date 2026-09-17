# Sprint 009 — primeiro artefato C99

## Protocolo

- artefato: `sha256:3ac80b0c480b2bf1eb86eccc1fa94bf80521ab97943f7abbefac0bc6a4ff7cad`;
- ABI: `casulo-native-abi/0.1`;
- benchmark: `casulo-native-benchmark/0.1`;
- operação: `WaterBalance`;
- lote: 2.000 registros `float64`;
- amostras: 15;
- iterações por amostra: 5;
- comparação: Python escalar versus C99, ambos com envelope completo.

## Resultado

| Caminho | ns/registro mediano | registros/s |
|---|---:|---:|
| Python escalar | 38.585,02 | 25.916,79 |
| C99 nativo | 9.749,56 | 102.568,73 |

- ganho de parede: `3,958×`;
- razão de CPU: `3,833×`;
- equivalência semântica: `true`;
- digest equivalente:
  `48d30adf31b4675ae1476c1eb785a9ef848c63ebe19f19c10450bd2f5f5775aa`;
- gate final `5×–20×`: ainda não atingido.

O arquivo [native-benchmark.json](native-benchmark.json) contém todas as
amostras, ambiente, comando portátil de compilação e SHA-256 do binário.

## Interpretação

O Sprint 009 prova que a linguagem T já atravessa uma fronteira AOT real e
conserva a manifestação Casulo. O custo restante está principalmente na
conversão Python → `ctypes` e na criação dos envelopes/evidências Python; esse
é o alvo explícito do Sprint 010.
