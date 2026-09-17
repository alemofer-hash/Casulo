module casulo.flood_rs.contracts

field TrainingEvidence
  trace dataset_sha256: Text
  trace validation_loss: Number
  trace backend: Text

condense EvidenceReady in TrainingEvidence
  judge validation_loss >= 0
  emit true
