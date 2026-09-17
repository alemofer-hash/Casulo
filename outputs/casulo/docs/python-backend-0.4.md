# Backend Python de referência 0.4

**Identificador:** `python-reference/0.4.1`
**Formato atual do pacote:** `casulo-artifact/0.8`
**Origem:** Teloscorp / Casulo

## Finalidade

O backend da Crisálida transforma uma CrisálidaIR válida em um módulo Python
determinístico e autocontido. O módulo usa somente a biblioteca padrão do
Python e não depende da IDE nem de uma instalação do pacote Casulo.

## Pipeline

```text
source.t
→ frontend Egg
→ análise Larva
→ CrisálidaIR canônica
→ backend Python
→ artefato endereçado por conteúdo
```

## Layout do artefato

```text
artefato/
├─ source.t
├─ crisalida.ir.json
├─ metamorfose.graph.json
├─ casulo_artifact.py
└─ manifest.json
```

- `source.t`: fonte integral recebida pelo compilador;
- `crisalida.ir.json`: significado tipado sem localização física;
- `metamorfose.graph.json`: dependências, efeitos e custo;
- `casulo_artifact.py`: execução autocontida;
- `manifest.json`: hashes, versões, operações, marca e origem.

O manifesto não contém relógio, caminho absoluto ou identificador aleatório.

## Identidade

O identificador é:

```text
sha256(
  formato do artefato
  + versão do compilador
  + versão do backend
  + hash da fonte
  + hash da IR canônica
  + hash do grafo
)
```

Fontes byte a byte idênticas produzem o mesmo identificador,
independentemente do diretório e do nome do arquivo.

## Cache

O segundo build só é considerado cache hit quando:

- o manifesto é idêntico;
- a fonte preservada é idêntica;
- a IR é idêntica;
- o executável é idêntico.

Um diretório existente que não satisfaça essas condições não é sobrescrito.

## Execução

```powershell
t build programa.t --output artefato
t run artefato --operation Operacao --input entrada.json
```

Quando existe uma única operação, `--operation` é opcional. Uma fonte também
pode ser executada diretamente; nesse caso `t run` realiza um build implícito:

```powershell
t run programa.t --input entrada.json
```

Uma lista JSON ativa automaticamente o kernel de lote. O modo também pode ser
exigido explicitamente:

```powershell
t run programa.t --input lote.json --batch
```

O cache escalar permanece local ao processo. O cache de lote nasce vazio em
cada chamada e é descartado ao final dela.

A identidade `casulo-structural-key/0.1` distingue `null`, booleano, inteiro,
float, texto, array e objeto. Objetos não dependem da ordem dos campos; arrays
preservam ordem; `1`, `1.0`, `true`, `+0.0` e `-0.0` permanecem distintos.

O fingerprint curto serve apenas como telemetria. A tabela usa a identidade
estrutural completa, de modo que colisões de hash são resolvidas por igualdade.
Para esquemas numéricos, o compilador materializa uma função de chave por
operação. Entradas irregulares usam o caminho estrutural genérico.

## Buffer tipado

Operações numéricas retilíneas podem declarar `casulo-typed-buffer/0.1`. O
backend separa a execução em:

```text
objetos recebidos
→ chaves estruturais
→ colunas contíguas float64 ou int64
→ índices e flags laterais
→ kernel sobre entradas únicas
→ manifestação dos envelopes na fronteira
```

Julgamentos e restrições usam `bytearray`; posições usam `array('I')`; colunas
usam `array('d')` ou `array('q')`. Resultados e valores estabilizados conservam
o tipo Python exato necessário para a manifestação.

O caminho só é usado quando todos os registros possuem exatamente o esquema
numérico e uma representação homogênea suportada. Tipos mistos, campos
adicionais, inteiros fora de 64 bits, estruturas opcionais ou operações com
controle incompatível retornam ao kernel de objetos. O fallback ocorre antes
de qualquer saída observável.

O campo `cache.hot_path` registra bytes efetivos dos buffers, células laterais
e estruturas intermediárias evitadas em relação ao kernel de referência.

O módulo gerado também possui uma CLI própria e não importa o pacote Casulo:

```powershell
python artefato/casulo_artifact.py Operacao entrada.json
```

Essa forma executa o módulo isoladamente. `t run` continua sendo a entrada
recomendada quando se deseja verificar toda a cadeia fonte → IR → executável
antes da execução.

## Validação JSON

Representações de referência:

| Tipo T | JSON/Python |
|---|---|
| `Number` | número, exceto booleano |
| `Bool` | booleano |
| `Text`, `Time`, `Date` | string |
| `Duration` | número ou string |
| `[T]` | lista validada recursivamente |
| `T?` | valor de `T`, `null` ou campo ausente |
| field | objeto com traces obrigatórios |

Campos adicionais são preservados. O backend não os descarta.

## Envelope

Uma emissão retorna:

```json
{
  "artifact_id": "sha256:...",
  "module": "casulo.flood_rs",
  "operation": "WaterBalance",
  "state": "stable",
  "input": {},
  "result": 0,
  "evidence": {
    "judgements": [],
    "restrictions": [],
    "projections": [],
    "bindings": [],
    "stabilized": []
  }
}
```

## Integridade e falhas

Antes de carregar o módulo, `t run`:

1. recalcula os hashes da fonte, da IR, do grafo e do executável;
2. recompila a fonte preservada;
3. compara novamente a IR canônica;
4. regenera e compara o executável;
5. regenera e compara o grafo def-use;
6. valida o índice de operações;
7. bloqueia caminhos que escapem do diretório do artefato.

Alterar um arquivo e apenas atualizar seu hash no manifesto não é suficiente
para passar por essa cadeia.

Códigos de saída:

| Código | Significado |
|---|---|
| `0` | build ou execução concluída |
| `1` | fonte T rejeitada por diagnóstico |
| `2` | entrada ou artefato inválido |
| `3` | execução bloqueada por schema, `judge` ou `restrict` |

## Limites conscientes

- o kernel tipado ainda executa o laço em Python, sem SIMD;
- não há paralelismo;
- não há sandbox de código Python;
- não há módulos `use` resolvidos;
- não há backend nativo;
- o cache operacional é local ao processo;
- não há invalidação persistente por nó do grafo.
