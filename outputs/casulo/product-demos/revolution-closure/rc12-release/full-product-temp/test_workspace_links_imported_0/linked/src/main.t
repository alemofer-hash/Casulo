language T/1.1
module demo.main
use demo.types
capability manifest

condense Main in Query
  effects [manifest]
  emit text
