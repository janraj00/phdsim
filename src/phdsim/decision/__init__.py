"""Public acquisition API, loaded lazily to keep domain imports independent."""

from importlib import import_module

_EXPORTS = {
    "Policy": ".policy", "choose_action": ".policy",
    "AlwaysAcquire": ".policies.always_acquire",
    "ExpectedGain": ".policies.expected_gain",
    "NoAcquisition": ".policies.no_acquisition",
    "RandomAcquisition": ".policies.random_acquisition",
    "UncertaintyThreshold": ".policies.uncertainty_threshold",
    "DecisionConfig": ".config",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
