"""Exercise both segmentation branches with the original architectures in inspection mode."""

from .trace import CallTrace


def run_pstnet(directory):
    from hashlib import sha256
    import json
    import numpy as np
    from PIL import Image
    import torch

    from phdsim.datasets.pst900.segmentation import load_frames
    from phdsim.decision.pstnet import FixedPstPolicy
    from phdsim.evaluation.segmentation import confusion_matrix, segmentation_metrics
    from phdsim.fusion.pstnet.model import PstFusion
    from phdsim.perception.pstnet.rgb import PstRgb
    from phdsim.perception.pstnet.features import rgb_features
    from phdsim.perception.pstnet.input import _verified_image, rgb_tensor, thermal_tensor, reference_mask
    from phdsim.runtime.segmentation import SegmentationReplay

    directory.mkdir()
    assets = {}
    for name, pixels in (
        ('rgb', np.full((36, 64, 3), (70, 100, 130), dtype=np.uint8)),
        ('thermal', np.full((36, 64), 110, dtype=np.uint8)),
        ('labels', np.zeros((36, 64), dtype=np.uint8)),
    ):
        path = directory / (name + '.png')
        Image.fromarray(pixels).save(path)
        content = path.read_bytes()
        assets[name] = {'path': str(path), 'bytes': len(content), 'sha256': sha256(content).hexdigest()}
    manifest = directory / 'manifest.json'
    manifest.write_text(json.dumps({'schema': 'phdsim-pst900-segmentation-v1',
                                   'records': [{'frame_id': 'test/inspection', 'split': 'test',
                                                'sequence_id': 'inspection', 'tick': 0, 'assets': assets}]}), encoding='utf-8')
    # Explicit inspection scenario. No checkpoint loader, network download or training.
    with torch.random.fork_rng():
        torch.manual_seed(42)
        rgb = PstRgb(3, 5)
        fusion = PstFusion(rgb)
    scenarios = []
    for pull in (False, True):
        trace = CallTrace()
        for function, explanation in (
            (load_frames, 'Odczyt metadanych bez otwierania obrazów ani maski'),
            (SegmentationReplay.predict, 'Jedna klatka: RGB → decyzja → opcjonalna fuzja'),
            (rgb_tensor, 'RGB do tensora 1×3×360×640'),
            (_verified_image, 'Otwarcie dostarczanego pliku i sprawdzenie SHA256'),
            (PstRgb.forward, 'Oryginalna sieć RGB tworzy pięć logitów dla każdego piksela'),
            (rgb_features, '19 cech dostępnych z samego RGB'),
            (FixedPstPolicy.acquire, 'Jawny wybór gałęzi: bez thermal albo z thermal'),
            (thermal_tensor, 'Dopiero po zgodzie: thermal, resize i inpainting zer'),
            (PstFusion.forward, 'Fuzja z już policzonym rgb_logits; bez ponownego uruchomienia RGB'),
            (reference_mask, 'Po predykcji: odczyt referencji wyłącznie do oceny'),
            (confusion_matrix, 'Macierz pomyłek pikseli'),
            (segmentation_metrics, 'Przeliczenie macierzy pomyłek na metryki'),
        ):
            trace.watch(function, explanation)
        with trace:
            frame = load_frames(manifest, verify=False)[0]
            prediction = SegmentationReplay(rgb, fusion, FixedPstPolicy(pull)).predict(frame)
            reference = reference_mask(frame.mask_path, frame.mask_sha256)
            segmentation_metrics(confusion_matrix(prediction.final_mask, reference))
        summary = {'inspection_only': True, 'weights': 'random initialization, seed 42',
                   'input': 'synthetic PNGs', 'acquired': prediction.acquired,
                   'transferred_bytes': prediction.transferred_bytes,
                   'output_shape': list(prediction.final_mask.shape),
                   'rgb_forward_calls': sum(s['name'] == 'PstRgb.forward' for s in trace.rows),
                   'fusion_forward_calls': sum(s['name'] == 'PstFusion.forward' for s in trace.rows)}
        scenarios.append({'title': 'PSTNet: ' + ('pobranie thermal' if pull else 'koniec po RGB'),
                          'intro': 'Tryb do czytania kodu: syntetyczna klatka i oryginalne architektury z losowymi wagami. '
                                   'Ten przebieg pokazuje kolejność oraz rozmiary danych; nie ocenia jakości wytrenowanego modelu. '
                                   'Obie gałęzie są wybierane jawnie przez FixedPstPolicy.',
                          'steps': trace.rows, 'summary': summary})
    return scenarios
