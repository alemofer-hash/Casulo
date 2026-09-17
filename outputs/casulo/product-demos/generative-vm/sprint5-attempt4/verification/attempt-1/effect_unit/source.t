language T/1.1
module effects

capability manifest

field EffectManifest
  trace value: Text

condense Apply in EffectManifest
  effects [manifest]
  emit "Cartografo de Duvidas - Effects: Memory Read"
