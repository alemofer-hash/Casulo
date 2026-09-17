language T/1.1
module scientific

capability manifest

field ScientificEvaluator
  trace value: Text

condense Evaluate in ScientificEvaluator
  effects [manifest]
  emit "manifest: memory.read, trace: 'Evaluating Einstein equations', effects: [manifest], emit: 'Scientific evaluation complete.'"
