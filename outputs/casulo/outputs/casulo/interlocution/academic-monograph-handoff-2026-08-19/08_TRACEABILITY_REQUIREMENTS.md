# Requisitos de rastreabilidade

Crie `EVIDENCE_TRACEABILITY.csv` com colunas:

```text
claim_id,claim_text,epistemic_class,status,chapter,primary_evidence,
evidence_fields,verification_method,adversarial_check,limitation
```

Regras:

- um claim central pode ter várias linhas, uma por evidência independente;
- não referencie apenas `report.md` quando existe JSON bruto;
- valores derivados devem mostrar fórmula e entradas;
- hash citado deve ser recalculado;
- `PASS` não pode ser inferido de ausência de erro;
- `null`, ausente e não mensurado permanecem distintos de zero;
- resultados históricos invalidados aparecem com status `INVALIDATED`, nunca
  são removidos;
- no mínimo 40 claims devem ser rastreados, incluindo todos os números do
  resumo e da conclusão;
- cada capítulo deve ter ao menos uma subseção `Base de evidência`.

Inclua em apêndice uma matriz que conecte pedido humano, requisito, política T,
TCAP, trabalho, receipt, verificador e publicação.
