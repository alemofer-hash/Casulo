# Sprint 019 — resultado oficial

| Comparação | Mediana pareada | IC95% independente | Veredito |
|---|---:|---:|---|
| Casulo/T ÷ PyTorch eager | `0,232910×` | `0,213952×–0,255515×` | `NEGATIVE` |
| Casulo/T ÷ PyTorch Inductor | `0,104399×` | `0,083294×–0,119623×` | `NEGATIVE` |

Todos os gates numéricos passaram. O resultado global é `NEGATIVE`, não existe
claim liberado e a energia elétrica permanece `null`.

O backend tensorial geral `0.1` está correto, mas não é competitivo neste
workload de álgebra linear densa. Os dados brutos permanecem em
`tensor-lab-report.json`; o HTML é apenas uma manifestação visual deles.
