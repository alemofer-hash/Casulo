# Errata da demonstracao live-v1

`live-v1` nao qualifica o passo de adulteracao do dataset. A recusa ocorreu por
colisao do scratch de entrada (`input T duplicado ou fora do scratch`), antes da
politica de identidade ser avaliada. Embora fail-closed, essa causa nao prova
`dataset_hash_mismatch`.

O attempt permanece preservado, mas seu `status=PASS` no resumo nao deve ser
usado como gate TI14. A demonstracao qualificavel e executada em novo diretorio
append-only e exige a causa literal `dataset_hash_mismatch`.
