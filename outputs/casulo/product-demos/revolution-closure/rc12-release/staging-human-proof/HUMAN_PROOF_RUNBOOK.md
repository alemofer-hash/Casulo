# Runbook curto — prova humana owner

1. Abra `VERIFY_RELEASE.vbs` e confirme `ready=true`.
2. Abra `START_CASULO_OWNER.vbs`; nenhuma API externa é usada.
3. Crie um ponto seguro com **Snapshot**.
4. Converse naturalmente; use **Falar (8 s)** como entrada primária e texto como fallback explícito.
5. Mantenha três projetos, introduza uma contradição e exija decisão humana.
6. Crie algo inédito; confirme que compilar e cumprir o pedido são julgamentos separados.
7. Interrompa, corrija, simule, materialize, exporte e reimporte.
8. Reinicie; confirme HOT vazio e memória reidratada.
9. Teste restore; feedback fica fora do overlay e deve sobreviver.
10. Use **Nota** ou `COLLECT_FEEDBACK.vbs` para registrar cada falha ou desejo.

Não use um prompt preparado pelo sistema. Somente Guilherme escolhe um resultado:

- `GUILHERME_HUMAN_PROOF_PASS`
- `GUILHERME_HUMAN_PROOF_CHANGES_REQUIRED`
- `GUILHERME_HUMAN_PROOF_ABORTED`

`PASS` não autoriza release comercial nem altera as fronteiras de Cloud, rede ou dispositivos.
