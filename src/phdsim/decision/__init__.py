"""Acquisition contract, concrete policies and their configuration factory."""

from .policy import Policy, choose_action
from .policies import AlwaysAcquire, ExpectedGain, NoAcquisition, RandomAcquisition, UncertaintyThreshold
from .config import DecisionConfig
