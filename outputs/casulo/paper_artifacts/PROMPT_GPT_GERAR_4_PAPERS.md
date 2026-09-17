# Prompt para gerar quatro versões do paper a partir da evidência

Você receberá o arquivo `GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE.zip`. Leia **todo** o pacote, incluindo manifest, hashes, código auditado, dados brutos, reanálise, matriz de afirmações, literatura e limitações, antes de escrever.

## Tarefa

Produza quatro manuscritos científicos tecnicamente equivalentes, em português, inglês, espanhol e francês, direcionados ao **Journal of Systems and Software**, com o autor exatamente como:

**Guilherme Moura Fernandes**

Não invente afiliação, e-mail, ORCID, titulação ou coautores. Preserve campos editáveis.

Use exatamente o título em português:

**A Linguagem T como otimização do gerenciamento do uso da CPU durante treinamento de Redes Neurais Artificiais**

Títulos equivalentes obrigatórios:

- English: **The T Language as an Optimization of CPU Usage Management During Artificial Neural Network Training**
- Español: **El lenguaje T como optimización de la gestión del uso de la CPU durante el entrenamiento de redes neuronales artificiales**
- Français: **Le langage T comme optimisation de la gestion de l'utilisation du processeur pendant l'entraînement de réseaux de neurones artificiels**

## Invariantes científicos

1. Fidelidade à evidência é universal e invariável. Nunca fabrique dado, referência, execução, energia, perfil, afiliação ou resultado positivo.
2. Equivalência vem antes de desempenho. Relate tolerâncias e diferenças numéricas.
3. Diferencie rigorosamente: evidência histórica, reanálise atual, hipótese causal e trabalho futuro.
4. O ganho histórico principal é específico ao FloodSurrogate e PyTorch Eager: mediana pareada 8,957846x, IC95% bootstrap [8,075179; 9,872416], n=21 pares.
5. O resultado Inductor é secundário: mediana 14,25558x, IC95% [12,496743; 15,383165], mas somente o forward foi compilado, o custo de compilação de 10,693516 s foi excluído, e o laço/backward/optimizer não foi fundido como passo completo.
6. Não use “6x” como afirmação sobre treinamento: 6,095936x pertence ao WaterBalance contra Python escalar, não ao PyTorch.
7. Energia elétrica não foi medida: `joules=null`. Não traduza tempo, CPU ou temperatura em economia de energia.
8. A tentativa térmica de 2 de agosto foi `BLOCKED_BEFORE_START`, com zero segundo de benchmark. Não a trate como amostra.
9. O caminho `learn` atual é um parser/gerador C especializado, separado do frontend/IR geral. Não afirme que o compilador geral da Linguagem T já aceita todo treinamento PyTorch.
10. Não afirme superioridade universal sobre PyTorch, Inductor, GPUs ou centenas de processadores.
11. Use o nome **Casulo** e as fases Egg, Larva, Crisálida, Metamorfose e Borboleta conforme o glossário. Não use nomes legados para o núcleo.

## Estrutura esperada

- resumo estruturado e palavras-chave;
- introdução com RQs e contribuições verificáveis;
- trabalhos relacionados baseados na triagem, conferindo os metadados antes da submissão;
- arquitetura com diagrama da cadeia de compilação e distinção do caminho especializado;
- metodologia reproduzível, equivalência, desenho pareado, warm-up, threads e pacto térmico;
- resultados com dados brutos, medianas, IC, teste de sinais como análise secundária e figura;
- análise causal e plano de ablações;
- energia: resultado explicitamente indisponível e protocolo futuro;
- ameaças à validade interna, externa, de construção e de conclusão;
- implicações de engenharia;
- conclusão prudente;
- declaração de disponibilidade do artefato como privado até decisão do autor;
- declaração de uso de IA a ser preenchida conforme a política editorial vigente.

## Entrega

Para cada idioma, entregue fonte LaTeX completa, referências BibTeX validadas e uma tabela que mapeie cada afirmação quantitativa ao arquivo de evidência. Não “melhore” números. Se houver conflito, obedeça ao dado bruto e documente a divergência. Marque claramente todos os campos humanos pendentes e todas as medições futuras.

