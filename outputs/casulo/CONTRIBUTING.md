# Contribuindo com o Casulo

Casulo é um invento da Teloscorp para otimização conservativa do tráfego de
informação. Contribuições são bem-vindas desde que preservem a lei central:
nenhum conteúdo recebido pode desaparecer sem manifestação explícita.

## Ambiente

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[science,dev]"
```

Em Linux/macOS, use `.venv/bin/python`.

## Verificação

```console
python -m pytest
python -m pytest --cov=casulo --cov-report=term-missing
t check examples/t/balanco_hidrico.t
t experiment examples/t/balanco_hidrico.t --output build/borboleta-smoke \
  --records 50 --samples 2 --iterations 1 --warmups 0
python -m build
python tools/normalize_sdist.py dist/casulo-*.tar.gz
python -m twine check dist/*
```

Mudanças no compilador devem incluir um caso golden ou um teste de propriedade.
Mudanças de desempenho devem anexar o JSON integral do experimento e nunca
publicar apenas o melhor tempo.

## Compatibilidade

A API Borboleta é candidata a estável durante a série `0.5.x`. Alterações
incompatíveis exigem nova versão do protocolo e uma nota de migração.
