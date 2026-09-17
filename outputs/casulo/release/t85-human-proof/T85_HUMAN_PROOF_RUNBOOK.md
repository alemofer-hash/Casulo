# Casulo T85 — roteiro de prova humana

1. Execute `VERIFY_CASULO_OWNER_T85.vbs`.
2. Execute `START_CASULO_OWNER_T85.vbs`; o fluxo comum não abre terminal.
3. Converse por texto ou autorize uma captura local de voz quando desejar.
4. Use `:universos`, `:rota`, `:memoria` e `:criar` para inspecionar fatos e criar.
5. Crie um ponto seguro com `:snapshot` antes de alterações relevantes.
6. `:restore` sem snapshot deve falhar de modo recuperável; com snapshot, afeta somente o overlay.
7. Use `:export` e o botão Nota para preservar feedback selecionado.
8. Encerre com `:sair` ou o botão Sair.

O modelo Qwen3-4B e o runtime llama.cpp permanecem no cache owner verificado.
Cloud, rede guest, USB, block devices e QPU permanecem bloqueados. A assinatura é
de desenvolvimento, não comercial. Qualidade de voz, química e design ainda
dependem da avaliação de Guilherme.
