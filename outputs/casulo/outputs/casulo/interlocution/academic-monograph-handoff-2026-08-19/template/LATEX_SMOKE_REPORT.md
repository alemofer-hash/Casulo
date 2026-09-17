# Relatório do exemplar editorial

- data: 2026-08-19;
- fonte: `smoke.tex` → `main.tex`;
- engine portátil: Tectonic 0.17.0;
- backend bibliográfico do smoke: BibTeX 8, somente por compatibilidade;
- contrato do build final: LuaLaTeX + Biber;
- páginas: 25;
- formato: A4, frente e verso;
- metadados: título, autor, assunto e palavras-chave conferidos;
- JavaScript/formulários/criptografia: ausentes;
- inspeção visual: capa, resumo, sumário, capítulo, equações, TikZ, tabela,
  listing, PGFPlots e referências;
- defeitos bloqueantes observados: zero;
- warnings tolerados no smoke: URLs longas na bibliografia e fallback BibTeX.

O MiKTeX local não foi usado como prova final porque seu `latexmk` depende de
Perl ausente e a primeira geração do formato LuaLaTeX não concluiu no tempo da
validação. A incompatibilidade entre Biber 2.21 do host e biblatex 3.17 do bundle
Tectonic impede validar Biber misturando essas distribuições. O PDF do smoke foi
compilado integralmente pela rota portátil; o agente final deve usar uma
distribuição coerente de LuaLaTeX, biblatex e Biber e registrar as versões.
