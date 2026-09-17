# Evidencia — Sprint 14 Product Alpha

Data: 2026-08-11

Estado: `PRODUCT_ALPHA_COMPLETE`

## Vertical slice owner

`product-demos/product-alpha-owner-sprint14-v2/alpha-report.json`

SHA-256: `ad2fbba09a7c607b5f92150e07906ec04232e8327df5536370cc65c6a4610d3b`

O fluxo executou owner direto, Guide Presence, policy/embedding first-party,
IntentDelta confirmado, T Forge, 12 estados, memoria DPAPI/restart/recall,
interrupcao, simulacao falha, correcao localizada, simulacao aprovada, pacote,
API fora do Casulo, importacao e reedicao. Permissions e hash de `identity`
foram preservados. Nenhum efeito real ou Cloud foi usado.

## Native

`product-demos/native-sprint13/native-acceptance.json`

SHA-256: `8cbee030054cf5a09ec13936cda2289d22196182a7d170bc0594684073a9afa7`

## Edicoes assinadas separadamente

- owner manifest: `561ed85196e78ed14447ae019ba1b648085fba706590009df96216141d5c4a3d`;
- public manifest: `32c24e6f48fcfb6f3314e6ad7f013e492d29ff734e8cafe6448f8e93afa75b36`;
- cloud manifest: `8dec951e16e6675ec5cca02ba0a74fd57e7a43c36565b6074677d871bec502f4`.

As tres assinaturas Ed25519 de desenvolvimento foram verificadas. Chaves
privadas ficaram fora do repositorio. O wheel public teve 6 arquivos,
content-tree SHA-256
`6ea3f750d844ec7e519a2f81c012b8b6fda2dcacb92712aba50cc8721284d9d5`
e zero achado privado/modelo/key.

## Gate final

`279 passed, 1 skipped, 42 subtests passed in 12.38s`; Rust/Cargo check passou;
auditorias do source e wheel public passaram; `git diff --check` sem erro.

O skip e o teste de symlink do Windows quando o privilegio correspondente nao
esta disponivel; os vetores de device path e confinamento de imagem passaram.

Nenhum benchmark cientifico, energetico ou comparacao PyTorch foi iniciado.
