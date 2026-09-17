# Model card — Casulo Semantic Router v1

- Proprietário/origem: Teloscorp, Guilherme Moura Fernandes.
- Papel: classificar uma consulta entre seis universos instalados.
- Arquitetura: Multinomial Naive Bayes, tokens de palavra e caracteres 4-gram.
- Treino: CPU local, determinístico, sem dependências externas.
- Dados: 36 exemplos sintéticos first-party; 18 treino, 6 validação, 12 teste.
- Conteúdo do usuário: nenhum.
- Upstream weights: nenhum.
- Licença dos dados/código: MIT-first-party-synthetic / MIT.
- Autoridade: proposta de rota somente; capability broker e verificadores
  determinísticos continuam soberanos.
- Limites: vocabulário pequeno, seis classes, conjunto de teste local reduzido;
  não é prova de generalização ampla.
- Rollback: remover/desabilitar o adapter e usar o roteador determinístico base.

Hashes e métricas canônicos estão em
`product-demos/revolution-closure/rc05-training/pilot/`.

