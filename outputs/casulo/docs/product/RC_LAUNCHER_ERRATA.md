# Errata — Windows Script Host e BOM UTF-8

## Falha observada

Na primeira abertura humana de `START_CASULO_OWNER.vbs`, o Windows Script Host
encerrou antes do launcher com:

```text
Linha: 1
Caract.: 1
Erro: Invalid character
Código: 800A0408
```

## Causa

O arquivo selado começava com os bytes `EF BB BF`. O WSH instalado no host
interpretou o BOM UTF-8 como token VBScript inválido. Nenhuma VM, modelo,
memória ou criação chegou a ser aberta.

## Correção e regressão

Os quatro launchers `.vbs` agora são emitidos em Windows-1252, sem BOM. Cada
launcher contém um modo de parse sem efeitos ativado somente por
`CASULO_LAUNCHER_DRY_RUN=1`. A regressão executa os quatro arquivos no
`cscript.exe` real e exige `CASULO_VBS_PARSE_PASS` com exit code zero.

O pacote anterior foi preservado em
`release/human-proof-superseded-vbscript-utf8-bom-attempt2/`; seu manifesto
continua `7a8b4c4f2e7538c40347ead4a9caed68b7031419695bad28d93c0919d10d13f2`.
Ele não é mais o candidato corrente.
