# Calibração da janela térmica e metrológica

O juiz selecionou 250 ms como a menor janela pré-registrada estável para o MLP
médio candidato neste host.

- sete amostras;
- 512 invocações por amostra;
- CV de 6,43%, com limite selado de 15%;
- paridade candidato versus NumPy: `PASS`;
- sessão térmica: `PASSED_TELEMETRY`;
- pico: 55 °C;
- warning e throttling: ausentes;
- odor, fumaça e ruído anormal: ausência atestada pelo operador;
- janela de 500 ms: não executada pela regra de parada pré-registrada.

Hashes SHA-256:

- pré-registro: `5d0f1e894b143668ab5fe5f456dbe7d0078f15135db268f9ffdf1c358dd7655d`;
- amostras: `172e443c5c320c807b0a2b90657557519cca5ef0c64315defccb9a81e91a53d8`;
- veredito: `57812731a820a64453d70a436a40602fdd314a60eca892cc8df2232d245a0299`;
- sessão térmica: `6431bd73e43722fd4a1ca4b328d9fdab1c85174f7042a3916336ea491667f6f6`.
- atestação física: `f60f440c8f8e872ff72a5fd3f17a55675b928a89d1de8ecbe7683d04d31eb8b6`.

Este resultado calibra uma janela. Ele não mede speedup, energia ou
superioridade sobre outro backend.
