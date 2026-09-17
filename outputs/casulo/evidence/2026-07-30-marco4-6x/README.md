# Evidência congelada — Marco técnico 6×

Este diretório transforma o resultado do Sprint 011 em um pacote curto,
visual e auditável. Ele não substitui os relatórios brutos: aponta para eles,
confere seus hashes e comunica exatamente o que foi medido.

## Resultado

No experimento `WaterBalance`, no mesmo Intel Core i5-1235U:

- Python escalar: `12.329,27 ns/registro`;
- Casulo/T nativo: `2.017,69 ns/registro`;
- ganho mediano pareado: `6,095936×`;
- IC95% pareado: `5,994133×–6,230838×`;
- 21 amostras pareadas;
- 2.000 registros únicos por amostra;
- equivalência semântica: preservada.

A forma executiva `6,10×` é somente o arredondamento do valor medido. A frase
recomendada é:

> Até 6,10× mais vazão computacional no experimento declarado, no hardware
> existente, com conservação verificável da informação.

O prefixo “até” e o escopo do experimento não devem ser removidos.

## Como abrir

Abra `index.html` diretamente no navegador. O arquivo é autocontido: não usa
CDN, fonte remota, telemetria ou servidor.

## Como auditar

Na raiz do repositório:

```console
python tools/verify_frozen_evidence.py
```

O verificador confere:

1. hashes dos relatórios científicos de origem;
2. correspondência entre o JSON congelado e os campos dos relatórios;
3. presença do mesmo JSON dentro da demonstração autocontida;
4. equivalência semântica e limites do intervalo de confiança;
5. ausência de recursos externos na demonstração.

## Limite

Este pacote prova um resultado local, reproduzível e falsificável. Não prova
ganho universal, economia de energia equivalente, substituição física de
processadores, desempenho do FLOOD-RS completo ou validade de patente.

Casulo é um invento original da Teloscorp para Otimização de Tráfego de
Informação.
