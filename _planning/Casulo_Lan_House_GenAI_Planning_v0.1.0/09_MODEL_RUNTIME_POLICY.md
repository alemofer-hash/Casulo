# Política de modelos e runtime

## Seleção

Não escolher modelo apenas por benchmark público. Avaliar candidatos no hardware real com o mesmo runtime, quantização e contexto.

Requisitos eliminatórios:

- licença compatível com uso familiar local;
- GGUF suportado pelo runtime congelado;
- português suficiente;
- saída estruturada confiável;
- tool calling ou aderência forte a JSON Schema;
- tamanho adequado a 16 GB;
- nenhuma execução remota oculta;
- hash e origem registrados.

## Perfis

### `general`

Conversa, documentos, planejamento e perguntas familiares.

### `builder`

Código, patch, testes e revisão. Pode ser o mesmo modelo se vencer a bateria.

### `fallback`

Modelo menor para saúde do serviço, sumarização simples e recuperação quando o principal falhar.

## Defaults de partida

```text
quantization: Q4 aproximado
context: 8192
parallel_generations: 1
model_binding: 127.0.0.1
network_download_at_runtime: false
offline_mode: true após provisionamento
```

Parâmetros de amostragem devem ser separados por tarefa e versionados. Ferramentas usam saída restringida por schema quando possível.

## Registro obrigatório

Preencher `manifests/model-registry.template.json` para cada modelo:

- nome e família;
- arquivo;
- tamanho;
- SHA-256;
- licença e URL;
- quantização;
- contexto testado;
- runtime/commit;
- resultados de qualidade;
- RAM, velocidade e temperatura;
- decisão e justificativa.

## Atualização

Um modelo novo entra como candidato, nunca substitui diretamente o ativo. Processo:

1. download deliberado;
2. hash/licença;
3. quarentena;
4. benchmark fixo;
5. testes de ferramenta e segurança;
6. promoção explícita;
7. rollback preservado.

