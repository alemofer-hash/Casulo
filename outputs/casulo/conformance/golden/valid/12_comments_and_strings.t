# Comentário de arquivo
field Message
  trace text: Text # comentário de linha

condense KeepHash in Message
  judge text == "valor # preservado"
  emit text
