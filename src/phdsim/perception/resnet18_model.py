"""One independently trained network for one sensing modality."""

import torch
from torch import nn
from torchvision.models import resnet18


class ResNet18Model(nn.Module):
    def __init__(self, modality: str, pretrained_state=None, trainable="layer4_and_head"):
        super().__init__()
        if modality not in ("rgb", "thermal") or trainable not in ("head", "layer4_and_head"):
            raise ValueError("Unsupported modality or trainable layers")
        self.modality = modality
        self.network = resnet18(weights=None)
        if pretrained_state is not None:
            self.network.load_state_dict(pretrained_state, strict=True)
        self.network.fc = nn.Linear(self.network.fc.in_features, 1)
        for parameter in self.network.parameters():
            parameter.requires_grad_(False)
        if trainable == "layer4_and_head":
            self.network.layer4.requires_grad_(True)
        self.network.fc.requires_grad_(True)

    def train(self, mode=True):
        super().train(mode)
        # Preserve pretrained BN statistics even while fine-tuning the last block.
        self.network.eval()
        self.network.fc.train(mode)
        return self

    def encode(self, image):
        net = self.network
        value = net.maxpool(net.relu(net.bn1(net.conv1(image))))
        return net.layer3(net.layer2(net.layer1(value)))

    def classify(self, encoded):
        value = self.network.layer4(encoded)
        return self.network.fc(torch.flatten(self.network.avgpool(value), 1)).squeeze(1)

    def forward(self, image):
        return self.classify(self.encode(image))
