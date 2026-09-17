# Pacote científico do paper da Linguagem T

Este diretório contém somente infraestrutura nova e isolada para auditar,
recalcular e empacotar evidências do repositório Casulo/Linguagem T. Ele não
altera resultados históricos, não executa benchmarks sem telemetria térmica
confiável e não publica qualquer conteúdo.

Artefatos finais esperados em `paper_artifacts/dist/`:

- `GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE.zip`
- `PROMPT_GPT_GERAR_4_PAPERS.md`

Fluxo:

```powershell
python paper_artifacts/scripts/analyze_results.py
python paper_artifacts/scripts/build_package.py
python paper_artifacts/scripts/verify_package.py
```

Os scripts usam apenas a biblioteca padrão de Python. Gráficos são SVG
regeneráveis; nenhuma dependência binária é exigida para a análise.
