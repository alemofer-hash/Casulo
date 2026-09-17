module casulo.flood_rs

field HydroCell
  trace precipitation: Number
  trace evapotranspiration: Number
  trace surface_flow: Number
  trace base_flow: Number

condense WaterBalance in HydroCell
  judge precipitation >= 0
  let storage_change = precipitation - evapotranspiration - surface_flow - base_flow
  stabilize storage_change
  emit storage_change
