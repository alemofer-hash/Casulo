# Handoff — Casulo Beta Owner

Estado técnico: `READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF`.

## Abrir

1. Dê duplo clique em `release/human-proof/VERIFY_RELEASE.vbs`.
2. Confirme `ready: true`.
3. Dê duplo clique em `release/human-proof/START_CASULO_OWNER.vbs`.

O launcher é GUI e usa `pyw.exe`; PowerShell não participa do caminho normal.
Os quatro launchers foram resselados em Windows-1252 sem BOM e interpretados
com sucesso pelo `cscript.exe` real deste host. O candidato anterior, com BOM
UTF-8, está preservado como evidência e não deve ser usado.
Use **Falar (8 s)** para entrada local por voz, ou o campo de texto como fallback.
Crie um snapshot antes de explorar. `RESTORE_CLEAN_STATE.vbs` restaura o overlay
sem remover feedback.

## Registrar

Use **Nota** na janela ou `COLLECT_FEEDBACK.vbs`. Por padrão, somente a nota
selecionada é persistida; PCM bruto e transcript integral permanecem ausentes.

## Selos

- release manifest: `b6bfaa8166b0b2174392be64c1936a266e8a8cd119c9c7a8ab5e38017c2c4196`;
- signature: `bd4f0309bfec4c210a27b3a9a1f0255df86f87e2329ebd268ec66fed05e3e782`;
- SHA256SUMS: `b5c820b66b24b30a07265b7182f1c5f684233c0f9cbb86d2ba511239c01ad42c`;
- `START_CASULO_OWNER.vbs`: `bb5d0759ce664b812e3dd66dcc50c984d02273789040a868eb4b8a1419c5ceea`;
- owner artifact: `547cc4047b5d7523dae28960dbaa67971bdf952ece4a9e7b2a9f14a9104f6a9a`;
- base VM: `74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b`.

Somente Guilherme pode encerrar a sessão como PASS, CHANGES_REQUIRED ou ABORTED.
