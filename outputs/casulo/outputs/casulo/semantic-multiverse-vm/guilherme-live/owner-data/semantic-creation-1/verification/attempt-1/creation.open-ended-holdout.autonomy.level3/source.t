language T/1.1
module autonomy

capability manifest

field Level
  trace value: Text

condense SetAutonomy in Level
  effects [manifest]
  emit "manifest: autonomy.level3; trace: 'Autonomy level set to 3'; effects: [manifest]; emit: 'Autonomy level 3 activated.'"
