# RFC QR-001 — Quantum-ready sem quantum-fake

Status: `DEFERRED_OPTIONAL_R_AND_D`.

O core admite o tipo abstrato:

```text
ComputeBackend = CPU | GPU | NPU | QuantumSimulator | QPU
```

`QuantumSimulator` usa hardware clássico e nunca satisfaz a capability `QPU`.
`quantum.qpu.submit`, Azure, credenciais, rede e workspace remoto permanecem
indisponíveis e deny-by-default. `SimulatedQubit` e `PhysicalQubit` são tipos
distintos; nenhuma conversão implícita existe.

Q# 1.31 está presente apenas como extensão VS Code. Não há CLI Q#, QPU nem
workspace Azure configurado. Não instalaremos QDK neste Goal. Futuro protótipo
exige sandbox/lock separados, resource estimate, problema específico, baseline
clássico, contrato de fidelidade, custo e decisão `ADOPT`, `DEFER` ou `REJECT`.

Nenhuma operação quântica entra no hot path owner e nenhuma simulação autoriza
claim de aceleração ou capacidade quântica.
