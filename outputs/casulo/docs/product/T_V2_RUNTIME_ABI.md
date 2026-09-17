# ABI do runtime T v2

Status: reference + runtime Rust produtivo + conformance Casulo Native PASS.

## Entrada

O runtime recebe diretório TCAP v2 verificado, `module::function`, JSON canônico
de input e conjunto de capability handles concedidos pelo host. Nenhuma
primitive recebe path arbitrário, shell ou grant textual.

## Observável canônico

```json
{
  "result": {"kind": "ok|error", "value": null},
  "state_delta": {},
  "requested_effects": [],
  "events": [],
  "jobs": [],
  "diagnostics": []
}
```

Reference, Rust e Native produzem o mesmo observável. Runtime ID, timestamp e o
hash que necessariamente os inclui são deliberadamente externos à comparação
semântica; todos os demais campos causais do receipt precisam coincidir.

## Runtime Rust

`t-runtime/` implementa uma VM de opcodes estruturados. Build atual:

```text
cargo build --manifest-path t-runtime/Cargo.toml --release --locked --offline
```

Dependências pinadas: serde 1.0.229, serde_json 1.0.145 e sha2 0.10.9. O
runtime verifica hashes e confinamento das seções antes de executar, aplica
step/deadline, collections limits, cancel, capabilities e falha em opcode não
reconhecido. Não contém eval ou shell.

## Receipts

Os três runtimes emitem `casulo.t-decision-receipt/2.0` integral, incluindo
source/IR/TCAP/input/output, effects, grants, foreign calls, predecessor e hash
do próprio receipt. As identidades são `reference-2.0`, `rust-2.0` e
`native-2.0` sob o namespace `t-runtime/`.

## Conformance Native

O ramdisk `casulo.native-t-v2-probe/1.0` carrega source, seções TCAP e um
request, nunca um resultado pré-computado. O kernel verifica hashes, identidade,
IR/code e opcodes antes de interpretar. Cinco decisões e uma exaustão de steps
foram comparadas com reference/Rust dentro de QEMU sem rede ou disco do host.

Limite honesto: este gate executa o interpretador no kernel do guest, isolado
pela VM, e não em ring 3. O CLI Rust ainda recebe grants textuais somente no
harness; o produto owner deverá fornecer handles autenticados no Trust Plane.
