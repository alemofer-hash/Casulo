# GUILHERME MOURA FERNANDES — T LANGUAGE PAPER EVIDENCE

Pacote científico privado, auditável e não submetido.

Título principal: **A Linguagem T como otimização do gerenciamento do uso da CPU durante treinamento de Redes Neurais Artificiais**

Autor: **Guilherme Moura Fernandes**

## Resultado central, formulado corretamente

No benchmark histórico FloodSurrogate (MLP 8→8→1, ReLU, MSE, SGD, 400 épocas, lote completo, float64, CPU e uma thread), o executor C especializado preservou parâmetros, predições e perda em relação ao PyTorch. Em 21 pares, a mediana histórica do speedup sobre PyTorch Eager foi 8,957846x, com IC bootstrap pareado de 95% [8,075179; 9,872416].

O resultado é específico ao workload, host e sessão. Ele não prova superioridade universal da Linguagem T. O comparador Inductor é secundário porque a implementação auditada compilou somente a passagem direta. Energia elétrica não foi medida.

## Como navegar

- `01_ARCHITECTURE/`: arquitetura real e cadeia causal.
- `02_PROTOCOL/`: protocolo definitivo e matriz de afirmações.
- `03_EVIDENCE/RAW/`: relatórios históricos originais e tentativa térmica bloqueada.
- `03_EVIDENCE/PROCESSED/`: reanálise regenerável, amostras e figura.
- `03_EVIDENCE/PROFILES/`: perfis estruturais, sem alegação de runtime.
- `04_IMPLEMENTATION/`: snapshot mínimo do código e das especificações auditadas.
- `05_LITERATURE/`: triagem de 35 trabalhos e seleção de periódico.
- `06_MANUSCRIPTS/`: quatro esqueletos LaTeX e PDFs compilados.
- `07_TESTS/`: resultado JUnit dos testes curtos de correção.
- `08_INTEGRITY/`: estado do repositório, ambiente, manifest e hashes.
- `SCRIPTS/`: análise e verificação regeneráveis.

## Reproduzir a análise

Na raiz do repositório original:

```powershell
python paper_artifacts/scripts/analyze_results.py
python paper_artifacts/scripts/build_package.py
python paper_artifacts/scripts/verify_package.py
```

Não rode benchmarks de desempenho sem telemetria térmica avançando e o pacto térmico satisfeito.

## Privacidade e publicação

Este pacote foi criado localmente. A construção não cria commit, não faz push, não publica repositório, não envia manuscrito e não paga taxa editorial.

