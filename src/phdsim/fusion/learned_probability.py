"""Frozen late fusion fitted on separate paired development recordings."""

from dataclasses import dataclass

from phdsim.learning.fusion.features import fusion_features
from phdsim.models.linear import LinearModel
from phdsim.probability import binary_entropy
from phdsim.perception.results import TaskResult


@dataclass(frozen=True)
class LearnedProbabilityFusion:
    model: LinearModel
    version: str

    def update(self, previous, incoming):
        if previous is None:
            return incoming
        if previous.target != incoming.target:
            raise ValueError('Cannot fuse different targets')
        if set(previous.observation_ids) & set(incoming.observation_ids):
            raise ValueError('Cannot fuse duplicate observations')
        evidence = previous.evidence + incoming.evidence
        if len(evidence) != 2 or {e.modality for e in evidence} != {'rgb', 'thermal'}:
            raise ValueError('Learned fusion needs exactly one delivered RGB and one thermal image')
        probabilities = {e.modality: e.probability for e in evidence}
        p = self.model.predict(fusion_features(probabilities['rgb'], probabilities['thermal']))
        versions = tuple(dict.fromkeys(previous.model_versions + incoming.model_versions + (self.version,)))
        return TaskResult(incoming.target, p, binary_entropy(p), previous.observation_ids + incoming.observation_ids,
                          versions, evidence)
