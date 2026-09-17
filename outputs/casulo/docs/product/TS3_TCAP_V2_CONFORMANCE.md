# TS3 — TCAP v2 e conformance produtiva

Estado: `TS3_TCAP_V2_CONFORMANCE_PASS`.

## O que foi executado

O mesmo programa funcional `owner.publish::decide`, com loop limitado, estado,
job, capability, effect e `Result`, atravessou três máquinas:

1. runtime de referência Python;
2. runtime produtivo Rust compilado offline;
3. interpretador Native dentro de guest QEMU sem rede e sem disco do host.

Cinco casos cobrem publicação, intenção não confirmada, HARD desconhecido,
cancelamento e capability ausente. Observáveis e todos os campos causais do
receipt coincidiram. Um sexto TCAP com `steps=1` foi rejeitado pelos três como
`RESOURCE_STEPS_EXHAUSTED`; Native publicou `EXECUTION_COUNT=0`.

## Falsificação

- mudança de source com hashes recalculados não pode ocultar divergência do IR;
- opcode desconhecido, mesmo com seções e identidade recalculadas, é rejeitado;
- effect não declarado/capability ausente falha antes do efeito;
- schema futuro não é reinterpretado;
- corrupção do ramdisk é quarentenada;
- replay puro preserva observável e receipt do runtime Rust.

## Regressão Native v1

Depois do gate v2, a imagem foi reconstruída com o ramdisk TCAP v1 padrão. O
boot Product Alpha voltou a passar todos os marcadores G1–G3, inclusive ring 3,
W^X, capability negativa e quarentena. Assim, a rota v2 é opt-in por tipo do
ramdisk e não substitui o release RC13 preservado.

## Limites

- o interpretador v2 Native deste gate roda no kernel do guest; isolamento em
  ring 3 para T/2.0 permanece hardening posterior;
- o CLI Rust recebe grants como CSV somente no harness; o owner deverá consumir
  handles não forjáveis do Trust Plane;
- o gate é de correção, não de desempenho, energia ou ciência;
- nenhuma superfície owner foi promovida na matriz de soberania neste sprint.

Evidência primária:
`product-demos/t85-sovereign-engine/ts03-tcap-v2-attempt5/native/native-conformance.json`.
