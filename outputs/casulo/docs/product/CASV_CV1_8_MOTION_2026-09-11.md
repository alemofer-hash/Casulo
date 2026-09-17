# CV1.8 — movimento inteiro exato e falsificação natural

Estado: `MOTION_ENGINEERING_PASS_COMPETITIVE_BRANCH_REJECTED`.

## Resultado principal

CASV/0.7 implementou compensação de movimento inteira, bounded e reversível.
O vetor custa dois bytes dentro do payload; T escolhe cada tile antes do commit;
um decoder independente reconstrói os bytes canônicos e recusa vetores fora do
raio, do quadro ou em keyframes.

O mecanismo funcionou no controle deslocado sintético. Nos três holdouts
naturais congelados antes da implementação, contudo, T não selecionou nenhum
dos candidatos de movimento. Todos os arquivos foram exatos, mas o CASV ficou
entre 71,23% e 78,37% maior que FFV1. O ramo foi rejeitado pelo gate já
registrado, sem ajuste retrospectivo.

## Protocolo pré-registrado

- protocolo: `casulo.casv-motion-preregistration/0.7`;
- SHA-256:
  `8da4b77d1a35d4aebf65b5ece1b72dfa5c98033f404f201b4503e398e26fa226`;
- fonte selada CASV/0.3:
  `4a6f7a82745f5690c77e5115033842a844c2ab698de06c7afc09233356f34d17`;
- canônico-fonte: 1.769.472 bytes,
  `afb40c79c9a6d3bb2b6a9a73800da4eb9a9a183ed3761eac2ded71d4d67b98`;
- holdouts: esquerda `x=0`, centro `x=88`, direita `x=176`, cada um com
  80×144, oito quadros e `YUV444P10LE`;
- tile 40, faixa 48, keyframe 8, raio 8, stride SAD 4, quatro finalistas;
- referência competitiva por caso: menor resultado exato entre zstd 19,
  FFV1 nível 3 e x265 lossless;
- vitória material exigia razão `<=0,90` em dois casos, média geométrica
  `<=0,90` e nenhum caso acima de `1,05`.

## Resultados naturais

Cada holdout possui 552.960 bytes canônicos e produziu 144 decisões de tile +
um juízo final T.

| Holdout | CASV/0.7 | Menor exato | Bytes | Razão CASV/ref. | Motion escolhido |
|---|---:|---|---:|---:|---:|
| esquerda | 104.785 | FFV1 | 61.197 | 1,712257 | 0 |
| centro | 108.699 | FFV1 | 62.473 | 1,739936 | 0 |
| direita | 110.291 | FFV1 | 61.833 | 1,783692 | 0 |

- vitórias materiais: `0/3`;
- média geométrica da razão: `1,7450477275671872`;
- pior razão: `1,7836915562887132`;
- engineering gate: `PASS`;
- competitive gate: `FAIL`;
- decisão congelada:
  `REJECT_MOTION_BRANCH_AND_ADVANCE_TO_CAUSAL_VISUAL_GRAMMAR`.

Todos os três candidatos, zstd, FFV1 e x265 foram reconstruídos aos bytes e
SHA-256 de seu holdout. O zlib adicional também passou, mas não participou da
escolha da referência madura.

## Anatomia da derrota

Foram examinados 13.104 vetores por holdout, em 126 tiles preditivos. Nenhum
vetor venceu o custo do melhor modo espacial. A seleção agregada dos 432 tiles
foi dominada por Paeth:

- esquerda: 143 Paeth e um temporal SUB;
- centro: 138 Paeth e seis zlib;
- direita: 99 Paeth, 34 zlib e 11 DC/XOR;
- motion selecionado: zero nos três casos.

O custo do container é pequeno: 164 bytes fixos, 44 por record e 5 por tile.
A lacuna não vem do índice. Ela vem do residual: movimento translacional único
por tile, com XOR ou subtração bytewise, não explica bem interpolação,
subpixel, transformação, oclusão, deformação, mudança luminosa e estrutura
multiescala do clip. FFV1 também explora contexto e entropia com muito mais
eficiência que zlib por tile.

## Causalidade T

No probe RGB8 com deslocamento conhecido:

- política normal: 9.968 bytes, 12 tiles motion;
- mutação somente T: 18.980 bytes, zero tiles motion;
- TCAP normal:
  `c62bb2cf9d780ff85bc8a5a34c36f8b2c885ca85aba8490bdf263e35ac1ff0c2`;
- TCAP mutado:
  `1cb0d5092c0b5abbc6bd70384b4f77ba1447a303641584ea4e82063a211cac80`;
- traces distintos:
  `f1147791eba63874c5650466a1b4126d502611a9eb39bea58c510e77ef5e5946`
  e
  `f3ec6fea9df812d7ca528676b797f401ff052a5289b483ce3a974bb8b1ec06f5`;
- ambos reconstruíram o mesmo SHA-256 canônico.

Isso demonstra causalidade do seletor, não eficácia natural.

## Evidência e validação

- pré-registro append-only:
  `C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-preregister-attempt1`;
- campanha:
  `C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-natural-holdouts-attempt1`;
- manifest: `dfccc684e60ae8e7af50677b6e73d2f646b29d44d86ea6fef8058166f9de26ca`;
- SHA256SUMS:
  `5af77284c32834852aec08885be292b0cdb4d9b82abc9c9f4f7744441423c0bd`;
- 393/393 entradas revalidadas;
- regressão de compressão: `103 passed, 620 deselected`;
- teste focal motion: `7 passed`;
- Ruff e compileall: `PASS`.

## Próximo ataque inevitável

Encerrar a escalada de preditores locais de pixels. O próximo gate deve testar
uma gramática visual causal em que regiões, bordas, planos, câmera, iluminação
e residual sejam entidades explícitas e versionadas. A hipótese só avança se
reduzir o residual em holdouts novos; não basta reconhecer objetos ou gerar uma
aproximação visual. A reconstrução final continua byte-exact.
