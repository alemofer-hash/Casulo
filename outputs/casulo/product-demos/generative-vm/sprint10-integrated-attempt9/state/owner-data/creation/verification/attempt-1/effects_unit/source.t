language T/1.1
module effects

capability manifest

field EffectsManifest
  trace value: Text

condense ApplyEffects in EffectsManifest
  effects [manifest]
  emit "effects[manifest]"
