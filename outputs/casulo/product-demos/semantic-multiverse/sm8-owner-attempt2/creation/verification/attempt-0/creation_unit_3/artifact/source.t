language T/1.1
module interface

capability manifest

field ReversibleMaintenance
  trace value: Text

condense Interact in ReversibleMaintenance
  effects [manifest]
  emit "Simulating reversible maintenance interface for simulated environment"
