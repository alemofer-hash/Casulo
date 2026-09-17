# Registro de riscos — Semantic Multiverse

| ID | Risco | Controle atual | Gate |
|---|---|---|---|
| SM-R1 | partição perde constraint | required fields + fallback completo | suficiência |
| SM-R2 | rota errada | filtros duros, top-k, margem e clarificação | routing |
| SM-R3 | capability aumenta | comparação source/destination + broker | TSM022 |
| SM-R4 | thrashing | quota, lease, hysteresis e prefetch degradável | pressure |
| SM-R5 | crescimento/duplicação | SHA-256, base+delta, GC dry-run | 20 sessões |
| SM-R6 | cancelamento publica tarde | transaction ID e commit condicionado | cancellation |
| SM-R7 | corrupção | hash mismatch e quarantine fail-closed | corruption |
| SM-R8 | prompt injection | manifesto não confiável, schema e effects negados | security |
| SM-R9 | output do modelo vira autoridade | planner propõe; runtime valida | owner slice |
| SM-R10 | simulação vendida como QPU | tipos/capabilities distintos | Quantum RFC |
| SM-R11 | privado vaza no public | builds e auditorias separadas | public audit |
| SM-R12 | regressão G10 | baseline/hash/launcher e regressão integral | SM10 |
| SM-R13 | disco abaixo de 25 GiB | doctor e projeção de pior caso | disk gate |
| SM-R14 | conteúdo em métricas | somente contadores/hashes | privacy |
| SM-R15 | visual inventa progresso | somente events/receipts reais | VM inspection |
| SM-R16 | renderer assume campo opcional | projecao tipada; `creation_id` canonico; schema futuro falha fechado | reinspection |
| SM-R17 | restore sem snapshot corrompe estado | existence check antes de `qemu-img`; recusa recuperavel | reinspection |
| SM-R18 | ferramenta depende implicitamente de `rg` | `rg` opcional + scanner Python limitado e sem shell | reinspection |

No reseal de 2026-08-13, SM-R16 a SM-R18 passaram regressao. O risco residual
e humano: quimica, voz e visual continuam `PROVISIONAL_OWNER_REVIEW_REQUIRED`.
