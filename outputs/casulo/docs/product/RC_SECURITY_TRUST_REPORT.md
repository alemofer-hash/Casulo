# RC10 — Segurança e trust

O ataque integrado cobre dados importados/prompts, promoção DATA→INSTRUCTION,
grants, confirmação material, QPU, comandos/paths no bridge, replay, resultado
tardio, ZIP traversal, mismatch de payload, codegen com efeito não declarado,
updates A/B assinados, tamper, downgrade, fronteira public/owner, Cloud locked,
guest network e block devices.

O `OfflineABUpdater` verifica assinatura Ed25519, hash, canal, origem, versão e
rollback floor antes de escrever no slot inativo. O payload nunca é executado
pelo updater; health é um contrato fornecido pelo chamador. A troca de CURRENT é
atômica e falhas preservam o slot anterior.

O fuzz é limitado, determinístico e registrado. Doubles aparecem somente em
unit/simulation tests declarados; não contam como prova do motor owner.
