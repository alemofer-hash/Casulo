# T85 supply chain e hardening

## Gate TS13

`TS13_SUPPLY_CHAIN_PASS` foi selado com zero P0/P1 no caminho suportado.

O `llama-server.exe` de 9.216 bytes foi identificado como o pequeno launcher PE
do release oficial b10362; seu import table aponta para
`llama-server-impl.dll` (10.064.384 bytes). `--version` retornou build 10362 e
commit abreviado `4801e3c56`. Os 51 arquivos do runtime correspondem exatamente
ao receipt de adoção, cujo SHA-256 é
`915c3a7ede5894f179b99d56d48c547949c75667731b865d4bfd279080bd52cc`.

As três editions foram reconstruídas com supply chains distintas; o public
wheel passou com zero componente privado e o Cloud permaneceu
`RELEASE_LOCKED`. O attack probe integrado, A/B update/rollback, downgrade,
tamper, replay/cancel, prompt injection, grants, guest network/block devices,
128 imports aleatórios, 64 mutações TCAP, junction físico e ADS passaram pelo
comportamento fail-closed.

Regressão focal: 67 PASS, 1 skip. O único skip é a criação física de symlink no
Windows (`WinError 1314`). Ele está registrado como
`NOT_EXECUTED_HOST_PRIVILEGE` e não conta como PASS; junction real, ADS real e a
negação do branch symlink seguem cobertos. A habilitação de Developer Mode ou
elevação não foi feita automaticamente.

Evidence manifest SHA-256:
`c988d49d0f9a7f6697708ec13928b73317dff3594d18a168e830536c32207905`.
