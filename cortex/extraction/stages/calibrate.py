from __future__ import annotations

import math
from dataclasses import replace
from time import perf_counter

from .state import PipelineState

_BOOTSTRAP_PLATT_SLOPE = 1.0
_BOOTSTRAP_PLATT_INTERCEPT = 0.0


def _calibrate_probability(probability: float) -> float:
    bounded = min(0.999, max(0.001, float(probability)))
    logit = math.log(bounded / (1.0 - bounded))
    calibrated = 1.0 / (1.0 + math.exp(-(_BOOTSTRAP_PLATT_SLOPE * logit + _BOOTSTRAP_PLATT_INTERCEPT)))
    return min(1.0, max(0.0, calibrated))


def calibrate_confidence(state: PipelineState) -> PipelineState:
    """Apply bootstrap Platt-style confidence calibration."""

    started = perf_counter()
    calibrated_items = []
    for item in state.items:
        confidence = _calibrate_probability(item.confidence)
        extraction_confidence = _calibrate_probability(item.extraction_confidence or item.confidence)
        calibrated_items.append(
            replace(
                item,
                confidence=confidence,
                extraction_confidence=extraction_confidence,
            )
        )
    next_state = replace(state, items=tuple(calibrated_items))
    return next_state.with_timing("calibrate_confidence", (perf_counter() - started) * 1000.0)
