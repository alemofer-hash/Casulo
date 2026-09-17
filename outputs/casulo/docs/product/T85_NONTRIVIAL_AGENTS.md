# TS7 — agentes T não triviais

## Resultado

`TS7_T_NONTRIVIAL_HOLDOUTS_PASS` foi obtido na tentativa append-only 7. O gate
integra execução hosted no runtime Rust T/2.0 e conformidade Native em três boots
QEMU isolados. A prova é automática; a prova humana continua `NOT_EXECUTED`.

## Holdouts congelados

| Caso | Agente neural | Requisitos HARD | Módulos | Funções | Receipts hosted | Native |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `data-01` | `data_validator_01` | original preservado; schema versionado; diagnóstico por rejeição | 3 | 11 | 11 | PASS |
| `interactive-01` | `t_interactive_01` | isolamento de projeto; barge-in; export editável | 3 | 11 | 11 | PASS |
| `technical-02` | `t_mass_balance` | unidades; conservação de massa; resíduo | 3 | 11 | 11 | PASS |

Os planos foram propostos pelo Qwen3-4B local, sem seed fixa, e possuem hashes
de saída e `StochasticTrace`. O modelo escolheu identidade, decomposição em
módulos, flags de constraints, diagnósticos e resumo. A camada determinística
derivou os eventos positivos diretamente dos IDs HARD congelados. Essa projeção
é uma guarda semântica: o modelo não declara que cumpriu o requisito.

Cada agente exerce records, enums, listas limitadas, `Result`, branches, estado,
loops bounded, jobs, cancelamento e uma capability `simulation` consentida. O
runtime executou onze funções por agente e emitiu receipts distintos e
encadeáveis. Não há `emit_literal`, `emit`, API externa, fixture, fake engine,
seleção de template por prompt ou replay no gate.

## Falsificações preservadas

- tentativa 1: sucesso textual `FALSE`; invalidada;
- tentativa 2: schema não confinava IDs HARD dinâmicos; invalidada;
- tentativa 3: guarda de overlap lexical era dependente de idioma; invalidada;
- tentativa 4: divergência de limite entre módulo e código de erro; invalidada;
- tentativa 5: evento positivo de outro caso atravessou a fronteira; invalidada;
- tentativa 6: resultado limpo, mas a ligação canônica era registrada e não
  obrigatória no gate; superseded antes do gate integrado;
- tentativa 7: ligação canônica tornou-se condição obrigatória e passou.

Falhas de preflight de testes e CLI também foram preservadas em diretórios
append-only separados; nenhuma delas produziu resultado de holdout.

## Evidência

- raiz: `product-demos/t85-sovereign-engine/ts07-nontrivial-holdouts-attempt7`;
- gate integrado: `integrated-gate.json`;
- regressão focal: 58 testes PASS;
- arquivos selados: 163;
- SHA-256 do manifesto: `3f346d0bcdc5d46099a25d4973cc6c92853f3420ca2a2a63041207cbdc6c7415`;
- modelo: `qwen3-4b-q4km-llamacpp-b10362`;
- SHA-256 do modelo: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`.

TS7 não eleva sozinho `S_authority` global. Ele prova que o mecanismo produtivo
consegue gerar e executar três agentes T não triviais sob fulfillment e publish
T, inclusive no backend Native aplicável.
