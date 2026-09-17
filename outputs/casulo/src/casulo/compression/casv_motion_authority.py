from __future__ import annotations

from typing import Any, Mapping

from .casv_motion_ir import MAX_MOTION_RADIUS, MOTION_TILE_MODES
from .casv_tile_authority import CASVTemporalTAuthority, CASVTileAuthorityError


class CASVMotionTAuthority(CASVTemporalTAuthority):
    """T authority over spatial, homologous temporal, and motion candidates."""

    module = "compression.casv_motion"
    authority_schema = "casulo.casv-motion-authority/0.7"
    trace_schema = "casulo.casv-motion-decision-trace/0.7"
    judge_scope = "casv:motion-archive"
    storage_modes = frozenset(MOTION_TILE_MODES)
    causal_scope = (
        "per_tile_spatial_temporal_or_motion_selection",
        "keyframe_reference_eligibility",
        "bounded_integer_motion_vector_selection",
        "complete_archive_reference_judgement",
    )

    @staticmethod
    def _digest(value: Any, label: str, *, zero_allowed: bool = False) -> None:
        if not isinstance(value, str) or len(value) != 64:
            raise CASVTileAuthorityError(f"{label} hash is invalid")
        if any(character not in "0123456789abcdef" for character in value):
            raise CASVTileAuthorityError(f"{label} hash is invalid")
        if not zero_allowed and value == "0" * 64:
            raise CASVTileAuthorityError(f"{label} hash is unexpectedly empty")

    @staticmethod
    def _validate_payload(payload: Mapping[str, Any]) -> None:
        CASVTemporalTAuthority._validate_payload(payload)
        integer_fields = (
            "motion_candidate_vectors",
            "motion_radius",
            "motion_xor_dx",
            "motion_xor_dy",
            "motion_sub_dx",
            "motion_sub_dy",
            "motion_xor_bytes",
            "motion_sub_bytes",
        )
        if any(type(payload.get(field)) is not int for field in integer_fields):
            raise CASVTileAuthorityError("motion candidate accounting is not integral")
        if type(payload.get("motion_available")) is not bool:
            raise CASVTileAuthorityError("motion availability is not boolean")
        radius = payload["motion_radius"]
        if not 1 <= radius <= MAX_MOTION_RADIUS:
            raise CASVTileAuthorityError("motion radius is outside bounds")
        if payload["motion_xor_bytes"] <= 0 or payload["motion_sub_bytes"] <= 0:
            raise CASVTileAuthorityError("motion candidate cost is not positive")
        xor_hash = payload.get("motion_xor_reference_sha256")
        sub_hash = payload.get("motion_sub_reference_sha256")
        if payload["motion_available"]:
            if payload["motion_candidate_vectors"] <= 0:
                raise CASVTileAuthorityError("motion candidates are missing")
            CASVMotionTAuthority._digest(xor_hash, "motion XOR reference")
            CASVMotionTAuthority._digest(sub_hash, "motion SUB reference")
            for prefix in ("motion_xor", "motion_sub"):
                dx = payload[f"{prefix}_dx"]
                dy = payload[f"{prefix}_dy"]
                if (dx, dy) == (0, 0) or abs(dx) > radius or abs(dy) > radius:
                    raise CASVTileAuthorityError("motion vector is outside bounds")
        else:
            if payload["motion_candidate_vectors"] != 0:
                raise CASVTileAuthorityError("unavailable motion carries candidates")
            if any(payload[field] != 0 for field in integer_fields[2:6]):
                raise CASVTileAuthorityError("unavailable motion carries vectors")
            CASVMotionTAuthority._digest(
                xor_hash, "motion XOR reference", zero_allowed=True
            )
            CASVMotionTAuthority._digest(
                sub_hash, "motion SUB reference", zero_allowed=True
            )
            if xor_hash != "0" * 64 or sub_hash != "0" * 64:
                raise CASVTileAuthorityError("unavailable motion carries reference")


__all__ = ["CASVMotionTAuthority"]
