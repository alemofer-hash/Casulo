# Handoff owner - Semantic Multiverse na VM

Estado: `READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION`  
Design e voz: `PROVISIONAL_OWNER_REVIEW_REQUIRED`

Este handoff preserva o owner generativo G10 e acrescenta uma camada
inspecionavel de universos semanticos. O modelo local propoe conteudo e rota;
schemas, capabilities, lifecycle, transicoes, T Forge, persistencia e
materializacao continuam deterministicos e deny-by-default.

## Inicio

Abra PowerShell e execute:

```powershell
Set-Location 'C:\Users\guimo\Documents\Codex\2026-07-28\ex\outputs\casulo'
python tools/casulo_semantic_multiverse.py doctor --repo .
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1
```

O doctor e somente leitura. O launcher usa diretamente a base G10 read-only e
cria apenas um overlay QCOW2 esparso em
`outputs/casulo/semantic-multiverse-vm/guilherme-live/state`; ele nao duplica a
base nem os pesos.

## Roteiro de inspecao

1. Converse livremente em pt-BR. O texto e o fallback explicito desta versao.
2. Digite `:criar`, descreva uma criacao inedita e forneca o comportamento que
   precisa aparecer.
3. Examine a rota neural proposta. Somente `CONFIRMO` autoriza validacao,
   geracao/reparo T e materializacao.
4. Use `:universos`, `:rota` e `:memoria` para ver catalogo, estados
   FROZEN/WARM/HOT, receipts e GC dry-run.
5. Use `:snapshot` antes de explorar uma mudanca e `:restore` para retornar ao
   snapshot `guilherme-semantic-live`.
6. Use `:nota` para registrar uma alteracao desejada e `:export` para gerar o
   pacote de feedback. `:sair` encerra sem apagar memoria confirmada.

O visual aberto apos `:criar` deriva somente de receipts reais. Ele e uma
direcao Stark + Jobs provisoria; nenhuma decisao estetica ou de quimica do Guia
e tomada em nome de Guilherme.

## Inspecao e recuperacao fora do launcher

```powershell
python tools/casulo_semantic_multiverse.py inspect `
  --state-root outputs/casulo/semantic-multiverse-vm/guilherme-live/state/owner-data/semantic-multiverse

python tools/casulo_vm.py `
  --base release/casulo-native-generative-interactive.img `
  --state-root release/semantic-multiverse/initial-owner-state `
  doctor

python tools/casulo_vm.py `
  --base release/casulo-native-generative-interactive.img `
  --state-root release/semantic-multiverse/initial-owner-state `
  restore clean-semantic-multiverse
```

O ultimo comando afeta somente o overlay inicial do handoff. Nao monta ou
escreve dispositivo fisico.

## Evidencia e limites

- modelo: Qwen3-4B Q4_K_M, Apache-2.0, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- runtime: llama.cpp b10362, MIT, executavel SHA-256
  `76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e`;
- inferencia neural local e estocastica: seed normal ausente, 142 eventos de
  stream no cenario integrado;
- rota integrada: seis universos visitados, cinco transicoes e 28 receipts de
  lifecycle; somente `materializacao` permaneceu HOT ao concluir;
- 20 sessoes de pressao compartilharam sete blobs imutaveis e publicaram 20
  deltas unicos; GC nao deletou material;
- regressao de produto: 241 passed, 1 skipped; build Native pinado aprovado;
- Cloud permanece `RELEASE_LOCKED`; public nao contem privados; USB, block
  devices, QPU e GC material permanecem negados.

A inferencia ainda ocorre no host first-party e nao dentro do guest. A voz
hosted G10 foi preservada, mas o launcher Semantic Multiverse atual usa texto.
O catalogo inicial tem seis universos first-party e indice lexical esparso; nao
e uma ontologia universal nem prova compressao universal. Equivalencia e
operacional e limitada aos invariantes registrados, nunca identidade textual ou
bit a bit.

O selo verificavel esta em
`release/semantic-multiverse/handoff/MANIFEST.json`; SBOM, atestacao de
desenvolvimento e `SHA256SUMS` ficam no mesmo diretorio.

## Reseal e roteiro atual (2026-08-13)

O caminho acima descreve o primeiro selo e permanece historico. Para a
reinspecao atual, use somente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1
```

O launcher executa o doctor read-only antes de abrir a sessao e usa o estado
limpo `outputs/casulo/semantic-multiverse-vm/guilherme-reinspection-2026-08-13`.

1. Inicie.
2. Execute `:restore` antes de criar snapshot e confirme a recusa recuperavel.
3. Execute `:snapshot`.
4. Execute `:universos`.
5. Crie um agente inedito com `:criar`.
6. Confirme a rota proposta.
7. Observe geracao, diagnostics, reparo, simulacao e materializacao.
8. Execute `:export` e `:sair`.
9. Reinicie e confirme HOT vazio e memoria retomada.
10. Execute `:restore` para retornar ao snapshot.
11. Registre sua avaliacao com `:nota`.

O selo corrente fica em
`release/semantic-multiverse/handoff-reinspection-2026-08-13/`. O manifesto
tem SHA-256 `31764546c2dff61f68d2b00bbe4f78060cef4d1523234e7ad59ab1c24d9ad724`.
A assinatura e `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`. O selo anterior
foi marcado superseded, mas nenhum arquivo historico foi alterado.
