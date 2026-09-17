# Stage Zero — preservação, Git e arqueologia

## Princípio

O conteúdo consolidado em `C:\Users\guimo\Downloads\ex` deve ser preservado antes de qualquer reorganização. Os repositórios antigos foram removidos conscientemente pelo proprietário; não tentar recuperar, mesclar ou inferir seus históricos.

## Fase A — inventário somente leitura

Execute `scripts/00-preflight-readonly.ps1` e preserve o relatório. Examine:

- total de arquivos e bytes;
- arquivos acima de 100 MB;
- extensões dominantes;
- `.git` residuais;
- espaço livre;
- versões instaladas;
- virtualização e WSL;
- portas relevantes já ocupadas.

## Fase B — classificação

Classifique sem apagar:

1. fonte ativa provável;
2. testes;
3. documentação/arquitetura;
4. experimentos e provas;
5. modelos/pesos;
6. artefatos gerados;
7. ambientes/caches;
8. segredos/dados privados;
9. duplicatas ou versões divergentes;
10. material não identificado.

O material não identificado é preservado até decisão humana.

## Fase C — segredo e `.gitignore`

Use `templates/gitignore.casulo.txt` como ponto de partida. Não ignore lockfiles, fontes, testes, documentação ou fixtures pequenas. Não imprima valores secretos no chat ou nos relatórios.

## Fase D — commit bruto

Após revisão humana do staging:

```powershell
Set-Location -LiteralPath 'C:\Users\guimo\Downloads\ex'
git init -b main
git add -A
git status --short
git diff --cached --stat
git commit -m "chore(stage0): preserve consolidated Casulo source baseline"
git tag -a casulo-stage0-raw-2026-09-17 -m "Raw baseline before Casulo Family RP0.1 audit"
git fsck --full
git status
```

Não executar automaticamente o commit sem inspecionar `git status` e o diff staged.

## Fase E — backup real

Um commit no mesmo SSD não protege contra falha física. Em outro dispositivo:

```powershell
git bundle create 'E:\CasuloBackup\casulo-stage0-raw-2026-09-17.bundle' --all
git bundle verify 'E:\CasuloBackup\casulo-stage0-raw-2026-09-17.bundle'
Get-FileHash 'E:\CasuloBackup\casulo-stage0-raw-2026-09-17.bundle' -Algorithm SHA256
```

Substitua `E:` somente por destino explícito verificado. Nunca use sincronização destrutiva ou `/MIR` como primeiro backup.

## Fase F — baseline pós-snapshot

Somente após o snapshot:

- executar testes sem corrigir;
- registrar versões e resultados;
- identificar o núcleo canônico;
- produzir mapa de componentes e dependências;
- criar branch `rp0.1-family`;
- reorganizar em commits pequenos.

## Gate

```text
STAGE_ZERO_COMPLETE
raw_commit=<sha>
tag=casulo-stage0-raw-2026-09-17
bundle_verified=true
git_fsck=true
working_tree_clean=true
secrets_staged=0
```

