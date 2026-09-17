language T/1.1
module casulo.science.einstein

capability manifest

field EinsteinProblem
  trace value: Text

condense EvaluateResidual in EinsteinProblem
  effects [manifest]
  emit "Einstein local residual cbe302cf8a6fccd8"
