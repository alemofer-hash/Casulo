# Evidência Sprint 1

Comando:

```powershell
python -m pytest -q tests/product
python -m casulo.product.demo
```

O demo produziu `CreationSpec` v4 em `CONFIRMATION`, hash canônico
`dfcb7084cd63db4f6c2e9a31ed5c9899a3d9d2bc183240e17939b3483dcd0f14`,
quatro eventos encadeados, reidratação da versão 1 e bloqueio de grant implícito.

Invariantes testadas: delta proposto não muta, rejeitado é preservado,
base-version conflitante falha, capability só cresce por aprovação humana,
migração 0.1→1.0 é determinística e serialização canônica possui golden.

Resultado: `SPRINT_1_PASS`; P1 `PASS` para o slice de referência.
