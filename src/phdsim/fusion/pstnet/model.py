"""Original PSTNet fusion stream with an explicit, reusable RGB early exit.

Layer names, operations and confidence normalization match upstream. Only the
constructor's hidden CUDA/filesystem loading is replaced by dependency injection.
See third_party/pst900/NOTICE.md for attribution and GPL-3.0 license.
"""

import torch
from torch import nn
from .blocks import DownsamplerBlock, non_bottleneck_1d, UpsamplerBlock


class PstFusion(nn.Module):
    def __init__(self, rgb_net, num_classes=5):
        super().__init__()
        self.rgb_net = rgb_net
        for parameter in self.rgb_net.parameters():
            parameter.requires_grad_(False)
        # ================== ENCODER ==================
        self.initial_block_enc = DownsamplerBlock(9, 32)

        self.layers_enc = nn.ModuleList()
        self.layers_enc.append(DownsamplerBlock(32,64))

        # Encoder 5 Stack
        self.layers_enc.append(non_bottleneck_1d(64, 0.03, 1)) 
        self.layers_enc.append(non_bottleneck_1d(64, 0.03, 1)) 
        self.layers_enc.append(non_bottleneck_1d(64, 0.03, 1)) 
        self.layers_enc.append(non_bottleneck_1d(64, 0.03, 1)) 
        self.layers_enc.append(non_bottleneck_1d(64, 0.03, 1)) 
        
        self.layers_enc.append(DownsamplerBlock(64,128))
        # Encoder 2 Stack
        # 1)
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 2))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 4))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 8))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 16))
        # 2)
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 2))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 4))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 8))
        self.layers_enc.append(non_bottleneck_1d(128, 0.3, 16))

        # ================== DECODER ==================
        self.layers_dec = nn.ModuleList()
        self.layers_dec.append(UpsamplerBlock(128,64))
        self.layers_dec.append(non_bottleneck_1d(64, 0, 1))
        self.layers_dec.append(non_bottleneck_1d(64, 0, 1))

        self.layers_dec.append(UpsamplerBlock(64,16))
        self.layers_dec.append(non_bottleneck_1d(16, 0, 1))
        self.layers_dec.append(non_bottleneck_1d(16, 0, 1))

        # Final output
        self.output_conv = nn.Sequential(
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True),
            nn.Conv2d(16, num_classes, 3, 1, 1)
        )
        

    def forward(self, rgb, thermal, rgb_logits=None):
        if rgb_logits is None:
            rgb_logits = self.rgb_net(rgb)
        # Upstream normalizes ALL logits of each image together (not softmax).
        low = rgb_logits.amin(dim=(1, 2, 3), keepdim=True)
        span = rgb_logits.amax(dim=(1, 2, 3), keepdim=True) - low
        if not torch.isfinite(rgb_logits).all() or (span == 0).any():
            raise ValueError("Invalid RGB confidence volume for PSTNet fusion")
        confidence = (rgb_logits - low) / span
        output = self.initial_block_enc(torch.cat((confidence, thermal, rgb), dim=1))
        for layer in self.layers_enc:
            output = layer(output)
        for layer in self.layers_dec:
            output = layer(output)
        return self.output_conv(output)
