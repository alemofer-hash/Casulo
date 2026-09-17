# Qualificação física do host para energia

**Estado terminal:** `BLOCKED_HWINFO_INTERVAL`

Causa primária: new HWiNFO samples failed the frozen 250 ms polling gate

Causas secundárias:
- BLOCKED_BACKGROUND_ACTIVITY: preflight CPU utilization exceeds median 5% or p95 15%
- BLOCKED_OBSERVER_OVERHEAD: append-only watcher exceeds its frozen CPU or memory budget

Nenhum TCAP, PyTorch Eager, build, teste, compilação ou empacotamento foi executado.

CSV: `C:\Users\guimo\Documents\Codex\2026-07-28\ex\outputs\casulo\benchmarks\results\2026-08-02-sprint025-ablation\hwinfo-live-ablation.CSV`
Polling mediano/p95: 0.251 / 0.27515 s
Plano congelado: {'guid': '381b4222-f694-41f0-9685-ff5bb260df2e', 'name': 'Equilibrado'}
AC/bateria: PASS
Idle de 20 minutos: NOT_STARTED

A campanha energética não foi iniciada.
