# Casulo Owner — candidato de prova humana

Este pacote é uma **assinatura de desenvolvimento**, não um release comercial.

- motor: `OwnerGenerativeEngineAdapter`, inferência neural local;
- bootstrap: Qwen3-4B Q4_K_M, Apache-2.0, pesos verificados no cache owner;
- runtime bootstrap: llama.cpp b10362, MIT;
- base VM: imutável; dados owner em overlay esparso;
- Cloud: `RELEASE_LOCKED`;
- rede guest: desligada;
- USB e block devices: proibidos;
- QPU: indisponível e negada;
- áudio bruto e transcript integral: não persistidos por padrão;
- prova humana, química, voz e estética: pendentes de Guilherme.

Execute primeiro `VERIFY_RELEASE.vbs`. O verificador não modifica a criação.
