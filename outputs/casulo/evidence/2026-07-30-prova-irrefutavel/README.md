# Casulo/T — primeira cadeia do Pacto Científico

## Veredito

`INCONCLUSIVE`

O resultado contra PyTorch eager foi positivo, mas o baseline
`pytorch-compile-inductor-cpu`, obrigatório no pré-registro, ficou
indisponível. O Casulo/T recusou promover a parcela favorável a uma alegação
ampla.

## Resultado observado

| Item | Valor |
|---|---:|
| PyTorch eager CPU | 337,0635 ms |
| Casulo/T C99 fundido | 35,3111 ms |
| ganho mediano pareado | 8,957846× |
| IC95% independente | 8,075179×–9,872416× |
| pares | 21 |
| equivalência | aprovada |
| qualidade | aprovada |
| energia elétrica | não medida |

## Baseline ausente

`torch.compile(..., backend="inductor", fullgraph=True)` falhou com
`InductorError`: o compilador MSVC `cl.exe` não foi encontrado.

Essa falha está preservada em `pytorch-compile-probe.json`. Ela não é tratada
como derrota do PyTorch nem como vitória do Casulo/T.

## Cadeia

- `preregistration.json`: hipótese e desenho selados antes da medição;
- `pytorch-compile-probe.json`: indisponibilidade preservada;
- `verdict.json`: primeiro veredito, preservado antes da normalização LF;
- `verdict-v2.json`: mesmo veredito e métricas, vinculado ao arquivo
  normalizado que será distribuído pelo Git;
- relatório medido em
  `benchmarks/results/2026-07-30-scientific-covenant-eager/`.

Verificação:

```console
t scientific-verify \
  --preregistration evidence/2026-07-30-prova-irrefutavel/preregistration.json \
  --report benchmarks/results/2026-07-30-scientific-covenant-eager/training-report.json \
  --probe evidence/2026-07-30-prova-irrefutavel/pytorch-compile-probe.json \
  --verdict evidence/2026-07-30-prova-irrefutavel/verdict-v2.json
```

O primeiro veredito não foi apagado quando a representação de fim de linha do
relatório mudou. Uma segunda cadeia foi emitida, como exige a regra de não
sobrescrever evidência.

Casulo é um invento original da Teloscorp para Otimização de Tráfego de
Informação.
