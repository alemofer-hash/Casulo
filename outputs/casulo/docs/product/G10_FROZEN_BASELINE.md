# Baseline congelado do owner generativo G10

Data do freeze: 2026-08-12/13 UTC  
Branch de desenvolvimento: `product/semantic-multiverse`  
Commit de origem: `df12e916c90d9bd2b966326275dc191573f38abd`

O worktree preexistente estava substancialmente modificado e foi preservado sem
`reset`, `clean`, `checkout` destrutivo, `git add -A` ou cópia de pesos/VMs.
Antes da primeira alteração deste Goal, `git status --short` possuía 167
entradas e o inventário completo `--porcelain=v1 -uall` possuía 10.419 linhas,
SHA-256 `9eced22aa5c2ee2cca83da34ec27dc4666d81d85844c5e60654c7861def3a45d`.

## Artefatos vinculantes

| Artefato | SHA-256 verificado |
|---|---|
| `release/generative-vm/handoff/MANIFEST.json` | `3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651` |
| `product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json` | `c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6` |
| `release/generative-vm/casulo-owner-generative-vm-g10-complete.zip` | `bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477` |
| `release/CASULO_OWNER_VM_INSPECT.ps1` | `e0452669dc33ce20320c59ccc4af94500561192cc9f52e9f8270fcea4fc0db12` |

O manifesto do pacote de Goal possui 12/12 entradas válidas. O PDF formal possui
4 páginas e SHA-256
`90c316a45e764956722a84a4a53dde5c5f7fadefa3a11b6fec0e662273823097`.

## Gates read-only executados

```text
G10 gate                         READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION
G10 steps                        16/16 PASS
handoff checks                   all true
owner model doctor               READY; mutations=false; network=false
VM doctor                        ready=true; base read-only; network denied
public source audit              12 files; zero private finding
Cloud                            RELEASE_LOCKED
external media                   NOT_IN_USE
original launcher smoke (:sair)  exit 0
```

O primeiro doctor do modelo recebeu por engano o diretório do candidato como
raiz e, corretamente, encontrou um caminho duplicado sem receipt. A repetição
com `%LOCALAPPDATA%/Casulo/cache/generative` passou; isso foi erro de invocação,
não divergência do baseline.

## Dependências congeladas

- Qwen3-4B Q4_K_M, Apache-2.0, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- llama.cpp b10362, MIT, executável SHA-256
  `76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e`;
- Casulo Native base SHA-256
  `74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b`.

Este documento congela evidência histórica. O Semantic Multiverse recebe novos
artefatos, launcher, overlay, manifests e hashes; nunca sobrescreve G10.
