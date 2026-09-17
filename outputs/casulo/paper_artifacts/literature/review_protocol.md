# Protocolo e síntese da literatura

## Escopo

A triagem cobre compiladores de aprendizado de máquina, linguagens/IRs para tensores, fusão e escalonamento, metodologia de benchmarking e mensuração de energia. Foram registrados 35 itens; 33 integram a base principal e 2 permanecem apenas como contexto periférico.

## Método

- Fontes preferidas: páginas oficiais de conferências, DOI do editor, proceedings oficiais e arXiv quando o trabalho não possui página editorial aberta adequada.
- Critério de inclusão: contribuição direta para arquitetura de compilação, execução de treinamento, metodologia de desempenho ou energia computacional.
- Critério de exclusão do núcleo: proximidade apenas temática, sem consequência direta para a hipótese ou método.
- A planilha é um mapa de triagem, não uma revisão sistemática exaustiva. Antes da submissão, autores, páginas, volumes e BibTeX devem ser validados pelo DOI/editor.

## Síntese

PyTorch 2, TVM, Ansor, MLIR, Halide, Glow e trabalhos de fusão mostram que ganhos provêm de mecanismos concretos: captura de grafo, lowering, especialização, fusão, planejamento de memória, escolha de schedule e kernels. Logo, o artigo do Casulo/T deve comparar mecanismos, não marcas.

A literatura de metodologia exige múltiplas repetições, warm-up explícito, distinção entre variabilidade dentro e entre sessões e estatística compatível com dados pareados. A literatura de energia reforça que tempo, utilização e energia não são sinônimos; a afirmação energética precisa de joules medidos e fronteira de sistema documentada.

## Lacuna formulada com prudência

A possível contribuição é estudar um contrato declarativo restrito que gera um executor CPU especializado e auditável, com equivalência julgada antes do desempenho. A novidade não pode ser afirmada somente pelo vocabulário de fases nem pelo resultado de uma MLP. Ela depende de demonstrar uma combinação técnica distinta, comparadores fortes, ablações causais e generalização controlada.

