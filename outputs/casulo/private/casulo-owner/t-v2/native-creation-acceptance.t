language T/2.0
module owner.native.creation_acceptance
budget steps 256
budget deadline_ms 1000
schema version 1

record NativeCreationAcceptanceInput
  member model_output_valid: Bool
  member creation_name: Text
  member function_name: Text
  member input_contract: Text
  member output_contract: Text
  member generated_t_source_sha256: Text
  member compiled_t_source_sha256: Text
  member artifact_tcap_hash: Text
  member simulation_status: Text
  member simulation_left: Int
  member simulation_right: Int
  member simulation_result: Int
  member expected_result: Int
  member effects_requested: Int
  member materialization_hash: Text
  member cancelled: Bool

fn decide(input: NativeCreationAcceptanceInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.model_output_valid else "creation_spec_invalid"
  requires input.creation_name == "SomeDoisNumeros" else "unsupported_creation_name"
  requires input.function_name == "SomeDoisNumeros" else "unsupported_function_name"
  requires input.input_contract == "numero1,numero2" else "input_contract_mismatch"
  requires input.output_contract == "resultado." else "output_contract_mismatch"
  requires len(input.generated_t_source_sha256) == 64 else "generated_source_identity_invalid"
  requires input.generated_t_source_sha256 == input.compiled_t_source_sha256 else "compiled_source_not_causal"
  requires len(input.artifact_tcap_hash) == 64 else "artifact_identity_invalid"
  requires input.simulation_status == "PASS" else "simulation_failed"
  requires input.simulation_left == 7 else "simulation_left_mismatch"
  requires input.simulation_right == 11 else "simulation_right_mismatch"
  requires input.simulation_result == input.expected_result else "simulation_result_mismatch"
  requires input.expected_result == 18 else "expected_result_mismatch"
  requires input.effects_requested == 0 else "real_effects_denied"
  requires len(input.materialization_hash) == 64 else "materialization_identity_invalid"
  return ok "ACCEPT_MATERIALIZATION"
