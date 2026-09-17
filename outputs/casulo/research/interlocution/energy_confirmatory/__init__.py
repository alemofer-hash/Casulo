"""Confirmatory energy metrology isolated from the Casulo product path."""

from .analysis import analyze_confirmatory_campaign, hierarchical_paired_bootstrap
from .metrology import (
    EnergyWindow,
    InstrumentManifest,
    MeterSample,
    integrate_energy_window,
    validate_instrument,
)

__all__ = [
    "EnergyWindow",
    "InstrumentManifest",
    "MeterSample",
    "analyze_confirmatory_campaign",
    "hierarchical_paired_bootstrap",
    "integrate_energy_window",
    "validate_instrument",
]
