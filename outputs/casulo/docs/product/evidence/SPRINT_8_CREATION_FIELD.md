# Evidência — Sprint 8 Creation Field Renderer

Data: 2026-08-11

Estado: `SPRINT_8_CREATION_FIELD_PASS_STRUCTURAL_VISUAL_QA_PENDING`

## Resultado

O Campo da Criação é uma projeção pura e determinística; ele não inicia jobs,
não cria grants e não inventa progresso. O slice manifesta:

```text
SILENCE -> FIRST_INTENT -> FIRST_FORM -> CONFIRMATION
```

- `SILENCE` não mostra nós ou atividade falsa;
- `FIRST_INTENT` mostra uma semente provisória ligada ao hash do `IntentDelta`;
- `FIRST_FORM` só aparece com artifacts reais do T Forge;
- `CONFIRMATION` acrescenta um contorno explícito sem alterar os artifacts;
- correções preservam posição e fingerprint de manifestações não afetadas;
- relações visuais vêm das dependências do receipt;
- não existe drag-and-drop ou canvas de blocos.

O HTML é autocontido, sem rede ou JavaScript, possui CSP `default-src 'none'`,
SVG acessível, escape de conteúdo e respeito a `prefers-reduced-motion`.

## Demonstração

Índice local:

`product-demos/creation-field-sprint8/index.html`

Páginas produzidas:

- `0-silence.html` — SHA-256 `0e7de28f69c119c086fc2a94a942df3254acb2416ee8377b337a4fd072de200f`;
- `1-first_intent.html` — SHA-256 `4e17942378b7bcfe33ae87bee26398cac66c83240f1fab4bbbfe612bbbd515c1`;
- `2-first_form.html` — SHA-256 `3cf31b948720ad9cb881197a1b83df7717a048bada4b1dac39d593a115d06d4b`;
- `3-confirmation.html` — SHA-256 `32825356afc7297ff606ea61ff19e98a0d72db00121acd91363debe694b62901`.

Comando:

```powershell
python -m casulo.product.creation_field_demo `
  --output product-demos/creation-field-sprint8
```

## Gate

Gate focal: `16 passed`. Gate integral: `237 passed, 42 subtests passed`.
Auditoria public: `12` arquivos, zero achado privado.

A tentativa de inspeção automatizada no navegador embutido falhou antes de
abrir a página porque os assets internos do controlador estavam ausentes. Isso
não foi ocultado nem substituído por browser externo; revisão visual humana
permanece aberta. Nenhum benchmark científico novo foi iniciado.
