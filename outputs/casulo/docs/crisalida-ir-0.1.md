# CrisálidaIR 0.1

**Identificador:** `crisalida-ir/0.1`
**Produtor:** compilador T da Teloscorp / Casulo
**Estado:** formato textual experimental, coberto por golden tests

## Finalidade

A CrisálidaIR é a primeira representação intermediária tipada do Casulo. Ela
separa significado da sintaxe e será o ponto de entrada para:

- passes de otimização;
- grafo incremental;
- geração Python;
- kernels vetoriais;
- runtime nativo.

A IR 0.1 não é executada diretamente. O backend de referência
`python-reference/0.2` a materializa como módulo Python autocontido.

## Invariantes

Uma CrisálidaIR só é produzida quando:

- léxico e parser não possuem erros;
- nomes foram resolvidos;
- tipos são compatíveis;
- operações emitem em todos os caminhos;
- tipos de emissão são consistentes.

## Estrutura

```text
IRProgram
├── version
├── module
├── uses
├── fields
│   └── traces tipados
└── operations
    ├── kind
    ├── input_type
    ├── target_type
    ├── output_type
    └── instructions
```

## Operações 0.1

- `let`
- `judge`
- `restrict`
- `stabilize`
- `emit`
- `project`
- `bind`
- `if`

## Exemplo

```text
crisalida-ir/0.1
module casulo.flood_rs

field HydroCell {
  precipitation: Number
  evapotranspiration: Number
  surface_flow: Number
  base_flow: Number
}

condense WaterBalance(HydroCell) -> Number {
  judge precipitation >= 0 : Bool
  %storage_change = let precipitation - evapotranspiration - surface_flow - base_flow : Number
  stabilize storage_change : Number
  emit storage_change : Number
}
```

## Formatos

Texto:

```powershell
t inspect programa.t --ir
```

JSON:

```powershell
t inspect programa.t --ir --format json
```

O JSON canônico gravado em um artefato remove apenas `span`, porque caminhos
físicos e posições de arquivo não alteram o significado executável. Isso
permite que fontes idênticas compiladas em diretórios diferentes produzam o
mesmo identificador.

## Estabilidade

Enquanto o identificador for `crisalida-ir/0.1`, golden tests devem detectar
qualquer alteração textual. Mudança incompatível exige novo identificador.

## Próximas extensões

- blocos básicos e identificadores estáveis;
- relações de def-use;
- estados `unknown`, `partial`, `stable` e `blocked`;
- pureza;
- efeitos;
- custo;
- forma de arrays;
- janelas temporais;
- regiões de memória;
- invalidação incremental por operação.
