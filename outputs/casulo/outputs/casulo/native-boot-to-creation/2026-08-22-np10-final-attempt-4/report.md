# Casulo Native boot-to-creation proof

Estado: `CASULO_NATIVE_BOOT_TO_CREATION_PROOF`.

Três boots independentes produziram a mesma CreationSpec por inferência Qwen3-4B dentro do kernel Native. Cada token foi julgado por T antes da publicação; a fonte T content-addressed foi compilada, simulada, executada com resultado 18, materializada e aceita por T. Um quarto boot cancelado publicou somente o primeiro token e não publicou artefato nem materialização.

Fronteira: prova bounded em QEMU/WHPX, CPU, greedy congelado e prompt congelado. Não é SO de uso diário, modelo frontier, benchmark de desempenho/energia, boot físico ou autorização de USB.
