"""Learning curves and fixed validation examples for the RGB pilot."""

from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch

from phdsim.evaluation.segmentation import CLASSES

PALETTE = np.array(((20, 24, 32), (255, 85, 65), (65, 210, 110), (70, 145, 255), (255, 210, 50)), dtype=np.uint8)
NAMES = ('Tło', 'Gaśnica', 'Plecak', 'Wiertarka', 'Survivor')


def _font(size):
    path = Path('C:/Windows/Fonts/arial.ttf')
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def plot_history(output, metadata):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    history = metadata['history']
    epochs = [r['epoch'] for r in history]
    figure, axes = plt.subplots(1, 2, figsize=(11, 3.7), layout='constrained')
    for scope, label in [('train', 'Trening'), ('validation', 'Walidacja')]:
        axes[0].plot(epochs, [r[scope]['weighted_cross_entropy'] for r in history], marker='o', label=label)
        axes[1].plot(epochs, [100 * r[scope]['miou'] for r in history], marker='o', label=label)
    axes[0].set(title='Błąd segmentacji', xlabel='Epoka', ylabel='Ważona cross-entropy')
    axes[1].axhline(100 * metadata['validation_background_baseline']['miou'], color='gray', ls='--', label='Walidacja: tylko tło')
    axes[1].set(title='IoU ze wszystkich pikseli, 5 klas', xlabel='Epoka', ylabel='mIoU [%]')
    for axis in axes:
        axis.set_xticks(epochs)
        axis.grid(alpha=.2)
        axis.legend()
    figure.savefig(Path(output) / 'learning_curve.png', dpi=150)
    plt.close(figure)


@torch.inference_mode()
def validation_examples(output, samples, before, model):
    model.eval()
    width, height, label_height = 320, 180, 24
    canvas = Image.new('RGB', (width * 4, 44 + len(samples) * (height + label_height) + 44), '#f4f5f7')
    draw = ImageDraw.Draw(canvas)
    masks, initial_masks, selected_masks = [], [], []
    for i, title in enumerate(('RGB', 'Maska referencyjna', 'Przed uczeniem', 'Wybrana epoka')):
        draw.text((i * width + 8, 12), title, fill='#111827', font=_font(18))
    for row, sample in enumerate(samples):
        frame = sample['frame']
        rgb = (sample['rgb'][0].numpy().transpose(1, 2, 0) * 255).round().astype(np.uint8)
        predictions = (sample['mask'][0].numpy(), before[frame.frame_id],
                       model(sample['rgb']).argmax(1)[0].numpy())
        masks.append(predictions[0].astype(np.uint8))
        initial_masks.append(predictions[1].astype(np.uint8))
        selected_masks.append(predictions[2].astype(np.uint8))
        tiles = [Image.fromarray(rgb)] + [Image.fromarray(PALETTE[p]) for p in predictions]
        y = 44 + row * (height + label_height)
        draw.text((8, y), f'{frame.sequence_id} | klatka {frame.tick}', fill='#374151', font=_font(14))
        for column, tile in enumerate(tiles):
            canvas.paste(tile.resize((width, height), Image.Resampling.BILINEAR if column == 0 else Image.Resampling.NEAREST),
                         (column * width, y + label_height))
    y = canvas.height - 30
    for i, (name, color) in enumerate(zip(NAMES, PALETTE)):
        x = 12 + i * 250
        draw.rectangle((x, y, x + 18, y + 18), fill=tuple(map(int, color)))
        draw.text((x + 25, y), name, fill='#111827', font=_font(15))
    canvas.save(Path(output) / 'validation_examples.png')
    np.savez_compressed(Path(output) / 'validation_masks.npz',
                        frame_ids=np.array([s['frame'].frame_id for s in samples]),
                        reference=np.stack(masks), before=np.stack(initial_masks), selected=np.stack(selected_masks))


def write_report(output, metadata, samples, before, model):
    output = Path(output)
    plot_history(output, metadata)
    validation_examples(output, samples, before, model)
    initial = metadata['history'][0]
    selected = metadata['selected_validation']
    baseline = metadata['validation_background_baseline']['miou']
    improved = selected['miou'] > initial['validation']['miou']
    beyond_background = selected['miou'] > baseline
    foreground = selected['foreground_mean_iou']
    lines = ['# Pilotaż segmentacji RGB PSTNet', '',
             f"{len(metadata['plan']['train_frame_ids'])} klatek treningowych, {len(metadata['plan']['validation_frame_ids'])} walidacyjnych, {metadata['config']['epochs']} epok, wejście 640×360.",
             f"Wybrana epoka: **{metadata['selected_epoch']}** według globalnego mIoU na walidacji. Czas ścienny uruchomienia: {metadata['elapsed_seconds']/60:.1f} minut.",
             'Czas obejmuje przerwy w wykonywaniu procesu; nie jest pomiarem czystej pracy CPU.', '',
             '| Pomiar | Trening mIoU | Walidacja mIoU |', '|---|---:|---:|',
             f"| Przed uczeniem dekodera | {100*initial['train']['miou']:.2f}% | {100*initial['validation']['miou']:.2f}% |",
             f"| Wybrana epoka | {100*metadata['selected_train']['miou']:.2f}% | {100*selected['miou']:.2f}% |",
             f'| Wszystko jako tło | — | {100*baseline:.2f}% |', '',
             f"Ważona cross-entropy walidacji: {initial['validation']['weighted_cross_entropy']:.4f} → {selected['weighted_cross_entropy']:.4f}.",
             ('Wynik walidacji poprawił się względem inicjalizacji.' if improved else 'Nie uzyskano poprawy mIoU walidacji względem inicjalizacji.'),
             ('Model przekroczył wynik przewidywania wyłącznie tła.' if beyond_background else 'Model nie przekroczył wyniku przewidywania wyłącznie tła.'),
             f'Średnie IoU czterech klas obiektów: **{100*foreground:.2f}%**.', '',
             '| Klasa | IoU walidacji |', '|---|---:|']
    lines += [f"| {name} | {100*selected['class_iou'][key]:.2f}% |" for name, key in zip(NAMES, CLASSES)]
    if selected['weighted_cross_entropy'] > initial['validation']['weighted_cross_entropy']:
        lines += ['', 'Pomimo wyższego mIoU wzrosła ważona strata walidacyjna. Oceny prawdopodobieństw według tej straty pogorszyły się; sama poprawa masek nie potwierdza jakości niepewności do akwizycji.']
    missing = [name for name, key in zip(NAMES[1:], CLASSES[1:]) if selected['class_iou'][key] == 0]
    if missing:
        lines += ['', f"Klasy z zerowym IoU: {', '.join(missing)}. Pilotaż nie daje jeszcze skutecznej segmentacji wszystkich klas."]
    lines += ['', '![Przebieg uczenia](learning_curve.png)', '', '![Przykłady walidacji](validation_examples.png)', '',
              'Przykłady to pierwsze sześć klatek z ustalonego wcześniej planu, bez wybierania według jakości predykcji.',
              'Pełne maski 640×360 tych przykładów, z indeksami klas 0–4 i identyfikatorami klatek: `validation_masks.npz`.',
              'Wagi enkodera pochodzą z ImageNet; dekoder zaczyna losowo. Uczona jest cała sieć RGB.',
              'Architektura i preprocessing pochodzą od autorów. Optymalizator, inicjalizacja i parametry tego treningu są naszym wyborem.',
              'To mały pilotaż i wynik na walidacji używanej do wyboru epoki; nie jest odtworzeniem wyniku publikacji ani oceną końcową.',
              f"Oficjalny test ({metadata['plan']['official_test_frames_unused']} klatek) pozostaje niewykorzystany.",
              f"{metadata['plan']['acquisition_reserved_frames']} klatki z osobnych rodzin pozostawiono na przyszłą akwizycję.",
              'Fuzja i polityka akwizycji nie były w tym pilotażu uczone.', '',
              f"Checkpoint: `{metadata['checkpoint']['path']}`.", 'Konfiguracja, podział, historia, macierze pomyłek i SHA256: `training.json`.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
