# Grafo da Metamorfose 0.1

**Identificador:** `metamorfose-graph/0.1`
**Origem:** Teloscorp / Casulo

## Finalidade

O grafo da Metamorfose torna explícito como a informação atravessa uma
operação T. Ele não substitui a CrisálidaIR; deriva dela.

```text
CrisálidaIR
→ definições e usos
→ dependências de dados
→ dependências de controle
→ efeitos
→ custo estrutural
```

## Nós

Cada nó possui:

- identificador estável;
- operação;
- caminho estrutural;
- instrução;
- nomes definidos;
- nomes usados;
- pureza local;
- efeito;
- custo estimado.

Nós de entrada definem os traces do field consumido. Um `let` define um nome
local. Guardas, evidências e emissões usam as definições mais recentes
visíveis em seu escopo.

## Arestas

- `data`: conecta a definição de um nome ao uso;
- `control`: conecta um `if` às instruções dos ramos controlados.

Escopos de ramo são copiados. Uma definição local de um ramo não vaza para o
restante da operação.

## Efeitos

| Instrução | Efeito |
|---|---|
| entrada | `read` |
| `let` | `pure` |
| `if` | `control` |
| `judge`, `restrict` | `guard` |
| `project`, `bind`, `stabilize` | `evidence` |
| `emit` | `manifest` |

Todas as expressões aceitas em T 1.0 são determinísticas. Por isso as
operações atuais podem ser memoizadas, ainda que produzam evidência local.

## Custo

O custo 0.1 é estrutural, não temporal:

- uma unidade por instrução;
- uma unidade por operador, chamada ou decisão de expressão;
- comprimento de listas literais entra no custo.

Ele serve para comparação e planejamento. Não representa ciclos de CPU,
latência ou energia.

## Inspeção

```powershell
t inspect programa.t --graph
t inspect programa.t --graph --format json
```

O artefato conserva a forma JSON em `metamorfose.graph.json`. Seu hash entra
na identidade do artefato.

## Limites

- não há nós SSA;
- não há nós phi;
- não há forma ou unidade científica;
- custo não foi calibrado contra hardware;
- o cache ainda ocorre por operação completa, não por subgrafo.
