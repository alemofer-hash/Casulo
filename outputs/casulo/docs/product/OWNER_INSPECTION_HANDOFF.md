# Handoff da inspeção owner generativa

Estado: `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION`

## Reinspecao Semantic Multiverse atual

O handoff G10 descrito abaixo permanece historico e intacto. A sessao atual e
o reseal Semantic Multiverse no estado
`READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1
```

O launcher executa primeiro o doctor read-only, usa um estado owner novo e
suporta `:criar`, `:universos`, `:rota`, `:memoria`, `:nota`, `:snapshot`,
`:restore`, `:export` e `:sair`. Comecar com `:restore` sem snapshot gera uma
recusa recuperavel, nunca traceback ou mutacao.

Manifesto: `release/semantic-multiverse/handoff-reinspection-2026-08-13/MANIFEST.json`,
SHA-256 `31764546c2dff61f68d2b00bbe4f78060cef4d1523234e7ad59ab1c24d9ad724`.
A assinatura e somente de desenvolvimento, nao release comercial.

## Iniciar

Na raiz do repositório, abra PowerShell e execute:

```powershell
.\release\CASULO_OWNER_VM_INSPECT.ps1
```

O launcher valida imagem, modelo e runtime, prepara base imutável + overlay
QCOW2, abre o Guia generativo local em pt-BR e mantém Cloud, rede do guest, USB,
clipboard e shared folders desligados.

## Comandos

- texto livre: conversa neural estocástica com o Guia;
- `Ctrl+C`: interrompe a geração sem consolidar resultado tardio;
- `:criar`: pede ideia e aceitação, gera/repara T, simula, materializa e abre a
  timeline visual de 12 estados;
- `:nota`: registra feedback textual sem alterar o produto;
- `:snapshot`: preserva o overlay atual;
- `:restore`: restaura o snapshot `guilherme-live`;
- `:export`: exporta feedback sanitizado e hashes;
- `:sair`: encerra o runtime preservando owner-data.

## Dados e restauração

- estado/snapshots: `outputs/casulo/generative-vm/guilherme-live/`;
- feedback: `outputs/casulo/generative-vm/guilherme-feedback/`;
- artifact owner: `release/generative-vm/casulo-owner-generative-vm-g10-complete.zip`;
- overlay limpo: `release/generative-vm/initial-owner-state/owner-overlay.qcow2`;
- selo: `release/generative-vm/handoff/MANIFEST.json`;
- evidência G10: `product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json`.

Áudio bruto não é persistido. Restore/reset afetam somente o overlay; a base
permanece read-only. O export de feedback não cria grants nem libera release.

## O que avaliar

Calor, ritmo, capacidade de discordar, memória, utilidade das perguntas,
qualidade do IntentDelta, criação T, reparo, forma visual e sensação de
colaboração. Registre qualquer atrito com `:nota`; os testes não aprovam química,
beleza ou voz em nome de Guilherme.

## Limitações honestas

- interface desta entrega é fallback textual; voz duplex Native ainda falta;
- inferência neural ocorre no host, por bridge first-party local;
- cada volta inicializa um boot curto do guest;
- design Stark + Jobs é provisório;
- assinatura é atestação de desenvolvimento, não release comercial;
- Cloud/public/USB permanecem bloqueados.

Este handoff prova uma primeira criação generativa inspecionável. Não prova
Native final, voz final, estética aprovada ou prontidão de distribuição mundial.
