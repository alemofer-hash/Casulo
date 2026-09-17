language T/1.1
module effects

capability manifest

field ManifestEffects
  trace value: Text

condense TrackEvidence in ManifestEffects
  effects [manifest]
  emit "TrackEvidence: Monitor and record evidence that supports or refutes hypotheses in the research process."
