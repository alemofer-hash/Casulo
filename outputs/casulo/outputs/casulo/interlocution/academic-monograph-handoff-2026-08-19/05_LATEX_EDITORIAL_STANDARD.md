# Padrão editorial LaTeX

## Engine e documento

- LuaLaTeX + Biber;
- KOMA-Script `scrbook`, A4, 11 pt, frente e verso, capítulos à direita;
- tipografia Libertinus/Latin Modern com fallback compilável;
- microtipografia, hifenização pt-BR e citações multilíngues;
- bibliografia `biblatex` autor-data;
- hyperlinks discretos, bookmarks e metadados sem rótulo de grau;
- equações numeradas por capítulo;
- `booktabs`, `longtable`, `tabularx`, `siunitx` e `cleveref`;
- TikZ/PGFPlots para diagramas e gráficos vetoriais;
- `listings` para T, Python, Rust, C e JSON, sem `shell-escape`.

## Identidade visual

Paleta print-safe: azul profundo, âmbar e teal em baixa saturação. Cor nunca é o
único canal semântico. O texto principal é preto; fundos coloridos ficam
restritos a boxes, listings e diagramas.

## Qualidade

- figuras legíveis em impressão cinza;
- tabelas sem linhas verticais salvo necessidade excepcional;
- legenda abaixo de figuras e acima de tabelas;
- fontes/artefatos citados na legenda;
- números com unidade em `siunitx`;
- URLs quebráveis e DOI normalizado;
- nenhuma referência/citação indefinida;
- overfull box acima de 5 pt deve ser corrigido ou justificado;
- PDF/A não deve ser alegado sem validação específica.

O projeto em `template/` é uma base editorial, não conteúdo final. Pode ser
refatorado mantendo estes invariantes.
