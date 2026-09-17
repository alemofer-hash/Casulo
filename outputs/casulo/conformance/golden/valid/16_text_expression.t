field Name
  trace first: Text
  trace last: Text

condense FullName in Name
  let full = first + " " + last
  emit full
