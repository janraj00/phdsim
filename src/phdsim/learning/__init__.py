"""Offline learning, separated by the quantity being fitted.

``fusion`` learns how delivered RGB/thermal probabilities combine.
``acquisition`` learns the expected value of requesting the other modality.
``models`` holds shared numerical estimators. ``samples`` and ``plan`` control
data roles; ``training`` assembles a frozen bundle; ``experiment`` evaluates it.
Runtime rules are implemented in ``phdsim.fusion`` and ``phdsim.decision``.
"""
