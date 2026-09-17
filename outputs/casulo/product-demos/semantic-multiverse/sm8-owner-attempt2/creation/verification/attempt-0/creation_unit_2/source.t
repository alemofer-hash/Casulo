language T/1.1
module data

capability manifest

field SimulatedVibrationData
  trace value: Text

condense Generate in SimulatedVibrationData
  effects [manifest]
  emit "Generating simulated vibration patterns for centrifugal pump analysis"
