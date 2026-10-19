"""The mirror preserves modality pixels and rejects inconsistent source references."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

import numpy as np
from PIL import Image

from phdsim.datasets.pst900.mirror import fetch_mirror


def png_bytes(pixels):
    stream = BytesIO()
    Image.fromarray(pixels).save(stream, format='PNG')
    return stream.getvalue()


def mirror_fixture(root):
    rgb = np.full((4, 6, 3), (20, 80, 140), dtype=np.uint8)
    thermal = np.arange(24, dtype=np.uint8).reshape(4, 6)
    mask = np.zeros((4, 6), dtype=np.uint8)
    mask[1:3, 2:4] = 4
    assets = {}
    for modality, pixels in (('rgb', rgb), ('thermal', thermal), ('labels', mask)):
        content = png_bytes(pixels)
        name = f'source/{modality}/frame.png'
        assets[modality] = {'name': name, 'bytes': len(content), 'crc32': zlib.crc32(content)}
        if modality == 'rgb':
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
    frame = {'source_split': 'test', 'filename': 'frame.png', 'assets': assets}
    rgba = np.dstack((rgb, thermal))
    return frame, rgba, thermal, png_bytes(mask)


class Pst900MirrorTests(unittest.TestCase):
    def test_reuses_original_rgb_and_extracts_missing_thermal_without_pixel_changes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame, rgba, thermal, mask = mirror_fixture(root)
            original_rgb = (root / frame['assets']['rgb']['name']).read_bytes()
            with patch('phdsim.datasets.pst900.mirror._download_public',
                       side_effect=lambda url, target: mask if '/annotations/' in url else png_bytes(rgba)):
                result = fetch_mirror(root, [frame])[0]
            self.assertEqual(result['original_assets'], frame['assets'])
            self.assertEqual(result['mirror']['original_pixel_comparisons'], ['rgb'])
            self.assertEqual((root / result['assets']['rgb']['name']).read_bytes(), original_rgb)
            with Image.open(root / result['assets']['thermal']['name']) as image:
                np.testing.assert_array_equal(np.asarray(image), thermal)
            self.assertEqual((root / result['assets']['labels']['name']).read_bytes(), mask)

    def test_rejects_mirror_pixels_or_masks_that_disagree_with_source_references(self):
        for mismatch in ('rgb', 'labels'):
            with self.subTest(mismatch=mismatch), TemporaryDirectory() as temporary:
                root = Path(temporary)
                frame, rgba, _, mask = mirror_fixture(root)
                if mismatch == 'rgb':
                    rgba[..., 0] = 255
                else:
                    mask = mask[:-1] + bytes([mask[-1] ^ 1])
                with patch('phdsim.datasets.pst900.mirror._download_public',
                           side_effect=lambda url, target: mask if '/annotations/' in url else png_bytes(rgba)):
                    with self.assertRaisesRegex(ValueError, 'differs from original'):
                        fetch_mirror(root, [frame])


if __name__ == '__main__':
    unittest.main()
