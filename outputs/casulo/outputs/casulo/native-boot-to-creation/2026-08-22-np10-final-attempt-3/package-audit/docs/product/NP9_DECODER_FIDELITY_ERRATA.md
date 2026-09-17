# Errata de fidelidade do decoder NP9

Data: 2026-08-22  
Estado: `SUPERSEDED_BY_NP10_CORRECTED_DECODER`  
Natureza: registro append-only; a evidência NP9 original não foi apagada nem
reescrita.

## O defeito

A implementação NP9 aplicava RoPE aos pares adjacentes do vetor Q/K. O Qwen3
adotado usa a convenção NeoX, que emparelha as duas metades do head. O primeiro
token podia coincidir porque ele ainda era calculado a partir do último token
do prompt congelado, mas tokens autorregressivos posteriores divergiam do
oráculo `llama.cpp`.

Consequentemente, NP9 não comprova fidelidade mult-token. Seus tokens a partir
da primeira realimentação autorregressiva ficam formalmente invalidados para
qualquer alegação de equivalência do decoder.

## O que NP9 ainda preserva

NP9 continua sendo evidência histórica útil da infraestrutura exercida naquela
tentativa: boot Casulo Native, transporte local do modelo, execução dos 36
blocos, emissão incremental de eventos, fronteira de cancelamento e integração
da presença. Isso não converte seus tokens divergentes em saída neural válida.

## Correção e prova substituta

O runtime Native passou a usar RoPE NeoX split-half. O decoder host Rust e o
kernel consomem a mesma regra matemática; o oráculo independente permanece o
`llama.cpp` owner congelado e não compartilha o código do decoder Casulo.

Para o prompt de criação congelado, o oráculo e o Native produziram exatamente
os 34 IDs:

```text
45,11408,28,8373,5404,285,67737,436,26,62721,5049,46,28,8373,5404,
285,67737,436,26,1825,49,32293,28,32615,16,11,32615,17,26,7778,
51171,28,32361,13
```

Decodificação:

```text
NOME=SomeDoisNumeros;FUNCAO=SomeDoisNumeros;ENTRADA=numero1,numero2;SAIDA=resultado.
```

Evidência substituta:

- oráculo host: `outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-3/creation-host-oracle.json`;
- três boots finais: `outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-11/normal-three-final.json`;
- cancelamento final: `outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-12/cancel-final.json`;
- imagem final: SHA-256
  `25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534`.

## Nota sobre telemetria serial

O boot executa primeiro o miniprobe histórico e, nessa fase local, registra
`CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO`. Depois o vertical slice NP10
consome o modelo completo e registra os estados agregados autoritativos
`CASULO_NATIVE_FULL_MODEL_RESIDENT=YES` e
`CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=YES`. O validador exige os marcadores
agregados posteriores; o `NO` anterior não descreve o estado final do boot.

## Limite da errata

A correção valida esta rota congelada e os seus controles causais. Ela não
prova equivalência para todo prompt, contexto máximo, sampling estocástico,
outros modelos, GPU/TPU ou inferência de produção.
