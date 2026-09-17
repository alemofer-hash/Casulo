# Evidência — Sprint 4 Living Memory

Data: 2026-08-11

## Gate

```text
167 passed, 42 subtests passed in 6.42s
public files scanned: 12
public forbidden findings: 0
cloud release state: RELEASE_LOCKED
```

## Demo reproduzível

```powershell
python -m casulo.product.memory_demo `
  --root .tmp-product-memory-demo/profile `
  --text "Quero um guia de enchentes para Porto Alegre"
```

Saída observada:

```json
{"events":1,"head_hash":"9f18b58a130233338bd12dd5ce4a0d8af83535b76a07be964233e5823dab9081","provenance":["demo:voice:1"],"recall_status":"FOUND"}
```

O conteúdo foi cifrado pelo DPAPI do usuário Windows, o processo foi reaberto e
a resposta foi derivada do evento persistido. Testes cobrem adulteração, cadeia,
quatro projeções, busca, ambiguidade, export, delete explícito e recusa de
criptografia de teste no modo produtivo.

## Limites

- V1 é single-writer por perfil; lock multi-processo é pré-release;
- export é plaintext apenas por ação explícita;
- não há sync remoto;
- nenhum modelo, voz, driver ou pacote foi instalado;
- nenhum benchmark científico novo foi iniciado.
