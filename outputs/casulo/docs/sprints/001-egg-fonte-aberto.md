# Sprint 001 — Egg: Fonte aberto

**Estado:** concluída localmente  
**Versão:** `0.2.0a1`  
**Data:** 29 de julho de 2026

## Objetivo

Criar o primeiro frontend aberto e reproduzível da linguagem T dentro do
repositório Casulo, sem depender de código presente apenas em um executável.

## Entregue

- especificação T 1.0;
- pacote `casulo.t`;
- `EggLexer`;
- `EggParser`;
- AST tipada e serializável;
- `LarvaAnalyzer`;
- diagnósticos estruturados;
- `t check`;
- `t inspect`;
- `t doctor`;
- entrada `t` em `pyproject.toml`;
- programa hidrológico canônico;
- 28 casos golden;
- testes do frontend;
- CI Windows/Linux para Python 3.11, 3.12 e 3.13;
- instalação limpa comprovada em ambiente virtual.

## Códigos diagnósticos

| Família | Fase |
|---|---|
| `T1xxx` | léxico e indentação |
| `T2xxx` | parser e estrutura |
| `T3xxx` | semântica |

## Validação realizada

### Ambiente de desenvolvimento

```text
16 testes executados
16 aprovados
0 falhas
```

O teste opcional de XLSX foi executado e aprovado no ambiente principal.

### Ambiente virtual limpo

```text
pip install -e outputs/casulo
t doctor
t check outputs/casulo/examples/t/balanco_hidrico.t
python -m unittest discover -s outputs/casulo/tests -v
```

Resultado:

```text
pacote casulo-0.2.0a1 instalado
programa canônico: ok
15 testes aprovados
1 ignorado: openpyxl opcional ausente
```

O caso ignorado pertence ao Casulo de arquivos e não ao compilador T.

## Gate

| Critério | Estado |
|---|---|
| Compilador-fonte dentro do repositório | aprovado para o frontend |
| Instalação em ambiente limpo | aprovado |
| `t doctor` | aprovado |
| `t check` | aprovado |
| AST inspecionável | aprovado |
| 20 ou mais golden tests | aprovado: 28 |
| Regressão do Casulo existente | nenhuma detectada |
| CI declarada | aprovado |
| Backend de execução | fora do escopo desta sprint |

## Limites conscientes

Esta sprint não implementa:

- resolução real de módulos `use`;
- tabela completa de símbolos;
- análise de tipos de expressões;
- emissão em todos os caminhos;
- IR;
- geração de Python;
- cache de compilação;
- `t build`;
- `t run`;
- arrays;
- backend nativo.

`t doctor` informa explicitamente a ausência de backend, evitando apresentar o
frontend como compilador completo.

## Decisões

1. A linguagem executável e a DSL de planejamento permanecem separadas.
2. T 1.0 mantém o núcleo pequeno já especificado.
3. Python será o primeiro backend de referência.
4. O backend nativo será comparado diferencialmente com o de referência.
5. Novas construções exigirão versão ou feature explícita.
6. As fases evolutivas nomeiam os componentes do compilador.

## Próxima sprint proposta

**Sprint 002 — Larva: Símbolos, tipos e IR**

Objetivo:

```text
AST
→ tabela de símbolos
→ resolução de nomes
→ verificação de tipos
→ CrisálidaIR textual
```

Gate:

```text
t check detecta nomes, tipos e caminhos de emissão
t inspect --symbols
t inspect --ir
golden tests diferenciais
```
