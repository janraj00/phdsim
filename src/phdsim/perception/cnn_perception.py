"""Run only the modality model corresponding to a delivered original image."""

from hashlib import sha256
from pathlib import Path

import torch

from phdsim.probability import binary_entropy
from phdsim.perception.results import PerceptionEvidence, TaskResult
from phdsim.core.identity import stable_id
from .baseline import ImagePayload
from .cnn_input import image_tensor, local_quality_features


class CnnPerception:
    def __init__(self, models, versions, config):
        if set(models) != set(versions) or not models:
            raise ValueError("Every modality needs its own frozen model version")
        self._models = dict(models)
        self._versions = dict(versions)
        self._config = config
        self._predictions = {}
        for modality, model in self._models.items():
            if model.modality != modality:
                raise ValueError("Model modality mismatch")
            model.eval().requires_grad_(False)

    @property
    def supported_modalities(self):
        return tuple(sorted(self._models))

    @property
    def version(self):
        return stable_id("resnet18-presence-v1", *(self._versions[m] for m in self.supported_modalities))

    def process(self, observation):
        if observation.modality not in self._models or not isinstance(observation.payload, ImagePayload):
            raise ValueError("CNN perception requires a supported delivered image")
        # A cached prediction never bypasses verification of the delivered bytes.
        payload = observation.payload
        if sha256(Path(payload.path).read_bytes()).hexdigest() != payload.sha256:
            raise ValueError("Delivered CNN image fingerprint mismatch")
        key = observation.modality, payload.sha256
        if key not in self._predictions:
            tensor = image_tensor(payload, observation.modality, self._config.image_height, self._config.image_width)
            with torch.inference_mode():
                probability = torch.sigmoid(self._models[observation.modality](tensor[None])).item()
            self._predictions[key] = probability, local_quality_features(tensor)
        probability, features = self._predictions[key]
        return TaskResult(observation.target, probability, binary_entropy(probability),
                          (observation.observation_id,), (self._versions[observation.modality],),
                          (PerceptionEvidence(observation.observation_id, observation.modality, probability, features),))
