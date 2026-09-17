language T/1.1
module casulo.revolution.materialization

capability manifest

record MaterializationDecision
  trace schema_valid: Bool
  trace tests_pass: Bool
  trace safety_pass: Bool
  trace bytes_match_hash: Bool

condense PublishArtifact in MaterializationDecision
  effects [manifest]
  if schema_valid
    if tests_pass
      if safety_pass
        if bytes_match_hash
          emit "PUBLISH"
        else
          emit "DENY"
      else
        emit "DENY"
    else
      emit "DENY"
  else
    emit "DENY"
