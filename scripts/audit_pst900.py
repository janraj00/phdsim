"""Read-only audit of frozen PST900 models. No fitting or threshold selection.

Writes one frame table, an audit summary and a self-contained visual gallery.
Run with Python 3.11+, numpy and Pillow, as for the experiment itself.
"""

from argparse import ArgumentParser
from collections import Counter, defaultdict
import base64
import csv
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phdsim.perception import ImageModel, image_features, load_observation
from phdsim.datasets import ObservationPool, digest, read_lines, write_json


def scores(rows, column):
    y = np.array([r["label"] for r in rows])
    p = np.array([r[column] for r in rows])
    positive, negative = y == 1, y == 0
    predicted = p >= 0.5
    tp = int(np.sum(predicted & positive))
    tn = int(np.sum(~predicted & negative))
    fp = int(np.sum(predicted & negative))
    fn = int(np.sum(~predicted & positive))
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    auc = None
    if positive.any() and negative.any():
        differences = p[positive, None] - p[negative][None, :]
        auc = float(np.mean((differences > 0) + 0.5 * (differences == 0)))
    bins = []
    for low in np.arange(0, 1, 0.1):
        selected = (p >= low) & (p < low + 0.1 if low < 0.89 else p <= 1)
        if selected.any():
            bins.append({"low": float(low), "n": int(selected.sum()),
                         "mean_probability": float(p[selected].mean()), "positive_rate": float(y[selected].mean())})
    return {
        "n": len(rows), "positive": int(positive.sum()), "negative": int(negative.sum()),
        "accuracy": (tp + tn) / len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "positive_predictions": int(predicted.sum()), "recall": recall, "specificity": specificity,
        "precision": tp / (tp + fp) if tp + fp else None,
        "balanced_accuracy": (recall + specificity) / 2 if recall is not None and specificity is not None else None,
        "auc": auc, "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(np.clip(p, 1e-12, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-12, 1)))),
        "mean_p_positive": float(p[positive].mean()) if positive.any() else None,
        "mean_p_negative": float(p[negative].mean()) if negative.any() else None,
        "probability_bins": bins,
    }


def png_preview(path, *, feature=False, mask=False):
    with Image.open(path) as source:
        if mask:
            image = Image.fromarray((np.asarray(source) == 4).astype(np.uint8) * 255)
            if np.count_nonzero(np.asarray(image)) == 1:
                y, x = np.argwhere(np.asarray(image) > 0)[0]
                left, top = max(0, int(x) - 15), max(0, int(y) - 15)
                image = image.crop((left, top, min(source.width, left + 16), min(source.height, top + 16)))
        else:
            image = source.convert("RGB" if source.mode == "RGB" else "L")
        if feature:
            image = image.resize((8, 8), Image.Resampling.BOX).resize((384, 216), Image.Resampling.NEAREST)
        else:
            image = image.resize((384, 216), Image.Resampling.NEAREST if mask else Image.Resampling.BOX)
        stream = BytesIO()
        image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def gallery(rows, output):
    test = [r for r in rows if r["split"] == "test"]
    chosen = {}
    # Exhaustive for the disputed RGB-only subset and all changed thermal decisions.
    for row in test:
        if row["rgb_correct"] and not row["thermal_correct"] or row["fusion_correct"] != row["thermal_correct"]:
            chosen[row["target_id"]] = row
    for predicate in (
        lambda r: not r["rgb_correct"] and r["thermal_correct"] and r["fusion_correct"],
        lambda r: not r["rgb_correct"] and not r["thermal_correct"],
        lambda r: r["label"] == 1 and r["rgb_correct"],
    ):
        for row in [r for r in test if predicate(r)][:2]:
            chosen[row["target_id"]] = row
    for split in ("train", "test"):
        positive = sorted((r for r in rows if r["split"] == split and r["label"]), key=lambda r: r["survivor_fraction"])
        if positive:
            row = positive[(len(positive) - 1) // 2]
            chosen[row["target_id"]] = row
    for row in rows:
        if row["split"] == "validation" and row["label"]:
            chosen[row["target_id"]] = row
    cards = []
    for row in chosen.values():
        tags = []
        if row["split"] == "validation":
            tags.append("validation")
        if row["split"] == "train":
            tags.append("train")
        if row["split"] == "test" and row["rgb_correct"] and not row["thermal_correct"]:
            tags.append("rgb-only")
        if row["split"] == "test" and row["fusion_correct"] and not row["thermal_correct"]:
            tags.append("repair")
        if row["split"] == "test" and not row["fusion_correct"] and row["thermal_correct"]:
            tags.append("damage")
        if row["split"] == "test" and not row["rgb_correct"] and not row["thermal_correct"]:
            tags.append("both-wrong")
        figures = []
        for name, key, options in (
            ("RGB", "rgb_path", {}), ("Thermal (AGC 8-bit)", "thermal_path", {}),
            (("Maska: powiększenie 16×16 z jedynym pikselem klasy 4" if row["survivor_pixels"] == 1 else "Maska klasy 4 — biały obszar"), "mask_path", {"mask": True}),
            ("RGB: część przestrzenna cech 8×8", "rgb_path", {"feature": True}),
        ):
            figures.append(f'<figure><img loading="lazy" src="{png_preview(row[key], **options)}" alt="{escape(name)}"><figcaption>{escape(name)}</figcaption></figure>')
        correct = lambda key: "dobrze" if row[key + "_correct"] else "BŁĄD"
        cards.append(
            f'<article data-tags="{" ".join(tags)}"><h2>{escape(row["target_id"])}</h2>'
            f'<p>Split: <b>{escape(row["split"])}</b>. Referencja: <b>{"Survivor obecny" if row["label"] else "brak Survivor"}</b>. '
            f'Obiekt: {row["survivor_pixels"]} pikseli ({row["survivor_fraction"]:.4%} kadru). '
            f'RGB: {row["rgb"]:.3f} ({correct("rgb")}), thermal: {row["thermal"]:.3f} ({correct("thermal")}), '
            f'średnia: {row["fusion"]:.3f} ({correct("fusion")}).</p><div class="grid">{"".join(figures)}</div></article>'
        )
    html = '''<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audyt PST900 — obrazy i błędy</title><style>
body{font:16px/1.5 system-ui;background:#101827;color:#e8edf7;max-width:1400px;margin:auto;padding:24px}
h1{font-size:28px}h2{font-size:17px;overflow-wrap:anywhere}article{border:1px solid #40516a;border-radius:12px;padding:18px;margin:20px 0;background:#172338}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}figure{margin:0}img{width:100%;display:block;background:black}figcaption{color:#b5c6df;padding-top:5px}
button{padding:9px 14px;margin:4px;border:1px solid #8dbbff;background:#203652;color:white;border-radius:6px;cursor:pointer}
button[aria-pressed=true]{background:#3267b0}small{color:#bdcce1}@media(max-width:650px){.grid{grid-template-columns:1fr}body{padding:12px}}
</style><h1>Audyt PST900: co naprawdę rozpoznają modele?</h1>
<p>Wszystkie 18 przypadków „RGB dobrze, thermal źle” i wszystkie 6 zmian poprawności względem thermal; dodatkowo kilka przykładów innych błędów, dodatnia klatka walidacyjna i przykłady bliskie medianie wielkości obiektu w train/test. To wybór diagnostyczny, a nie losowa próba.</p>
<p>Próg odpowiedzi „tak”: 0,5. Maska to oryginalna anotacja, przekształcona tylko do wizualizacji klasy 4. Miniatura pokazuje 8×8 średnich RGB; model używa też histogramów, średnich i odchyleń kanałów.</p>
<nav><button data-filter="all" aria-pressed="true">Wszystkie</button><button data-filter="rgb-only">RGB dobrze / thermal źle</button><button data-filter="repair">Fuzja naprawia thermal</button><button data-filter="damage">Fuzja psuje thermal</button><button data-filter="both-wrong">Oba modele źle</button><button data-filter="validation">Walidacja: 1 piksel</button><button data-filter="train">Przykład treningowy</button></nav><p id="count"></p>'''
    html += "\n".join(cards)
    html += '''<script>
document.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{
let count=0; document.querySelectorAll('article').forEach(card=>{const show=button.dataset.filter==='all'||card.dataset.tags.split(' ').includes(button.dataset.filter);card.hidden=!show;if(show)count++});
document.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.getElementById('count').textContent='Widoczne przykłady: '+count;
}));document.querySelector('button').click();</script></html>'''
    (output / "examples.html").write_text(html, encoding="utf-8")
    return list(chosen)


def overview(rows, output):
    test = [r for r in rows if r["split"] == "test"]
    predicates = (
        lambda r: not r["rgb_correct"] and r["thermal_correct"] and r["fusion_correct"],
        lambda r: not r["thermal_correct"] and r["fusion_correct"],
        lambda r: r["thermal_correct"] and not r["fusion_correct"],
    )
    selected = [next(r for r in test if predicate(r)) for predicate in predicates]
    selected += [r for r in rows if r["split"] == "validation" and r["survivor_pixels"] == 1][:1]
    width, row_height = 1536, 285
    canvas = Image.new("RGB", (width, 60 + len(selected) * row_height), "#101827")
    draw = ImageDraw.Draw(canvas)
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    font = ImageFont.truetype(str(font_path), 19) if font_path.exists() else ImageFont.load_default(size=19)
    draw.text((12, 10), "Audyt PST900: obrazy, referencja i miniatura 8×8", font=font, fill="white")
    for i, row in enumerate(selected):
        top = 60 + i * row_height
        heading = (f"{row['target_id']} | {row['split']} | klasa 4: {row['survivor_pixels']} px | "
                   f"pRGB={row['rgb']:.3f}, pT={row['thermal']:.3f}, średnia={row['fusion']:.3f}")
        draw.text((12, top), heading, font=font, fill="white")
        panels = (("RGB", "rgb_path", {}), ("Thermal", "thermal_path", {}),
                  (("Maska: zoom 16×16, 1 biały piksel" if row["survivor_pixels"] == 1 else "Maska klasy 4: biały obiekt"), "mask_path", {"mask": True}),
                  ("RGB 8×8: część cech modelu", "rgb_path", {"feature": True}))
        for column, (caption, key, options) in enumerate(panels):
            uri = png_preview(row[key], **options)
            with Image.open(BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
                canvas.paste(image.convert("RGB"), (column * 384, top + 30))
            draw.text((column * 384 + 8, top + 248), caption, font=font, fill="#b5c6df")
    canvas.save(output / "overview.png")


def write_report(summary, rows, output):
    metrics = summary["split_metrics"]
    pct = lambda value: "brak" if value is None else f"{100 * value:.2f}%".replace(".", ",")
    number = lambda value: "brak" if value is None else f"{value:.3f}".replace(".", ",")
    lines = [
        "# Audyt PST900: co wynika z obecnego eksperymentu", "",
        "Główne ustalenie: obecny model RGB słabo przenosi się na nagrania testowe. Średnia RGB/thermal "
        "nie poprawia trafności względem thermal, a pogarsza jakość prognoz prawdopodobieństwa. "
        "Dodatkowo wykryto problem doboru walidacji i wrażliwość definicji zadania na pojedynczy piksel maski.", "",
        "Audyt używa zapisanych, zamrożonych modeli i progu 0,5. Nie uczy modeli, nie dobiera progu, "
        "nie zmienia etykiet i nie zmienia dotychczasowych wyników. Obliczenia na treningu są "
        "oceną dopasowania do danych już użytych do nauki, a nie niezależną oceną skuteczności.", "",
        "## 1. Spójność danych i obliczeń", "",
        "Sprawdzono SHA256 wszystkich 800 obrazów i 400 referencji do masek, formaty i wymiary par, "
        "zgodność etykiet binarnych i liczników klas z pikselami masek oraz odciski danych treningowych modeli. "
        "Nagrania nie przechodzą między splitami. Przeliczone predykcje testowe odtwarzają zapisane wyniki "
        "z maksymalną różnicą " + str(summary["integrity"]["max_abs_difference_from_saved_test_predictions"]) + ". "
        "Kontrola nie dowodzi poprawności semantycznej wszystkich anotacji; wykrywa niespójność plików i obliczeń.", "",
        "## 2. Percepcja", "",
        "| Model | Trafność train (200) | Trafność test (160) | Wykryte dodatnie test | AUC test | Brier test ↓ |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, model in (("RGB", "rgb"), ("Thermal", "thermal"), ("Średnia", "fusion"), ("Zawsze «nie»", "always_no"), ("Stałe p z treningu", "training_prior")):
        train, test = metrics["train"][model], metrics["test"][model]
        lines.append(f"| {name} | {pct(train['accuracy'])} | {pct(test['accuracy'])} | {test['tp']}/{test['positive']} | {number(test['auc'])} | {number(test['brier'])} |")
    lines += ["", "AUC mierzy rozdzielanie klatek dodatnich od ujemnych bez wyboru jednego progu; "
              "0,5 odpowiada rankingowi losowemu. Wynik RGB bliski 0,5 oznacza, że problem na całym teście "
              "nie sprowadza się do progu odpowiedzi. To nie oznacza, że sama modalność RGB jest nieprzydatna.", "",
              "Model używa miniatury 8×8 i prostych statystyk obrazu. Nie uczy lokalizacji ani maski obiektu. "
              "Spadek jakości między train i test oraz różnice między nagraniami są obserwacjami. "
              "Zależność od tła, zbyt ubogie cechy i niedostateczny trening to hipotezy wymagające osobnych kontroli.", "",
              "## 3. Dlaczego średnia nie pomaga ponad thermal", "",
              "Na 160 klatkach: oba modele poprawne na 55, tylko thermal na 63, tylko RGB na 18, oba błędne na 24. "
              "Wszystkie 18 przypadków przewagi RGB to klatki bez Survivor — odpowiedź stała «nie» też byłaby "
              "tam poprawna. Ten licznik nie jest dowodem dodatkowej informacji semantycznej w modelu RGB.", "",
              "Średnia naprawia 3 błędy thermal i psuje 3 jego poprawne odpowiedzi, więc trafność pozostaje taka sama. "
              "Brier rośnie z " + number(metrics["test"]["thermal"]["brier"]) + " do " + number(metrics["test"]["fusion"]["brier"]) +
              ", a AUC spada z " + number(metrics["test"]["thermal"]["auc"]) + " do " + number(metrics["test"]["fusion"]["auc"]) + ". "
              "Zatem równa trafność nie oznacza równoważności obu rozwiązań.", "",
              "## 4. Walidacja i wielkość obiektu", ""]
    validation = [r for r in rows if r["split"] == "validation" and r["label"]]
    for row in validation:
        if row["survivor_pixels"] == 1:
            with Image.open(row["mask_path"]) as image:
                y, x = np.argwhere(np.asarray(image) == 4)[0]
            lines.append(f"Walidacja ma 39 etykiet ujemnych i jedną dodatnią. Dodatnia `{row['target_id']}` "
                         f"zawiera **dokładnie 1 piksel** klasy 4, w pozycji x={int(x)}, y={int(y)} "
                         "(indeksy od zera, prawa krawędź obrazu). Jest zgodna z obecną regułą «dowolny piksel klasy 4», "
                         "ale podejrzana jako przykład obecności obiektu. W podglądzie nie zidentyfikowano sylwetki; "
                         "nie zmieniono etykiety. Weryfikacja anotacji i reguły zadania jest konieczna przed strojeniem.")
    lines += ["", "Wszystkie trzy modele osiągają na tej walidacji 97,5%, odpowiadając zawsze «nie». "
              "Ten wynik nie potwierdza zdolności wykrywania obiektu.", "",
              "Mediana udziału obiektu w dodatnich kadrach: train " + pct(summary["positive_object_area"]["train"]["median"]) +
              ", test " + pct(summary["positive_object_area"]["test"]["median"]) + ". "
              "Obiekty testowe są więc typowo około czterokrotnie mniejsze powierzchniowo. "
              "Przy miniaturze 8×8 szczegóły małej sylwetki są silnie uśredniane z tłem. "
              "To zmierzona różnica danych i możliwa przyczyna trudności; audyt nie rozdziela jej wpływu od "
              "oświetlenia, sceny i rozmycia.", "",
              "## 5. Różnice między nagraniami testowymi", "",
              "| Nagranie | Klatki dodatnie / wszystkie | Trafność RGB | AUC RGB | Trafność thermal | Trafność średniej |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for sequence, data in summary["sequence_metrics"].items():
        if data["split"] == "test":
            rgb, thermal, fusion = [data["metrics"][m] for m in ("rgb", "thermal", "fusion")]
            lines.append(f"| {sequence} | {rgb['positive']}/{rgb['n']} | {pct(rgb['accuracy'])} | {number(rgb['auc'])} | {pct(thermal['accuracy'])} | {pct(fusion['accuracy'])} |")
    lines += ["", "Na `61_bag24` RGB ma 80% trafności, ale nie wykrywa żadnego z 8 obiektów — "
              "odpowiada zawsze «nie». Na różnych nagraniach ranking RGB też działa bardzo różnie. "
              "Dlatego sama łączna trafność ukrywa istotne problemy. Klatki z jednego nagrania są skorelowane; "
              "to 5 nagrań testowych, a nie 160 niezależnych eksperymentów.", "",
              "## 6. Następny krok", "",
              "1. Zweryfikować pojedynczy piksel anotacji i ustalić regułę obecności małego/uciętego obiektu. "
              "Potem przygotować train/validation z sensowną reprezentacją klas i rozmiarów, zachowując podział według nagrań.",
              "2. Sprawdzić percepcję RGB zachowującą lokalne cechy obiektu; porównać z obecnym modelem i stałą prognozą.",
              "3. Dopiero na sensownej walidacji porównać średnią z innymi fuzjami i politykami pobierania. "
              "Wyniki obejrzanego już testu traktować jako diagnostyczne; końcowe potwierdzenie wymaga osobnej, "
              "niewykorzystywanej do decyzji oceny.", "",
              "Artefakty: [galeria obrazów i masek](examples.html), [podgląd 4 przykładów](overview.png), [400 klatek z predykcjami](frames.csv), "
              "[pełne metryki i kontrola integralności](audit.json). Selekcja galerii jest jawna i diagnostyczna. "
              "Obrazy w galerii są zmniejszone; binarna maska i powiększenie pojedynczego piksela służą wyłącznie oglądaniu.", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(pool_path, results, output):
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Choose a new, empty audit directory: {output}")
    pool = ObservationPool(pool_path)
    sources = [pool.root / name for name in ("pool.json", "observations.jsonl", "labels.jsonl", "annotations.jsonl", "provenance.jsonl", "dataset.json")]
    sources += [results / name for name in ("models.json", "config.json", "summary.json", "predictions.csv")]
    before = {str(p): digest(p) for p in sources}
    snapshot = json.loads((results / "models.json").read_text(encoding="utf-8"))
    models = {m["modality"]: ImageModel(**{**m, **{k: tuple(m[k]) for k in ("center", "scale", "coefficients")}})
              for m in snapshot["perception"]["models"]}
    labels = pool.read_labels()
    annotations = {r["target"]["id"]: r for r in read_lines(pool.root / "annotations.jsonl")}
    by_target = defaultdict(dict)
    groups = defaultdict(set)
    for row in pool.records:
        by_target[row.target][row.modality] = row
        groups[row.split].add(row.sequence_id)
    for modality, model in models.items():
        training = [r for r in pool.records if r.split == "train" and r.modality == modality]
        fingerprint = sha256(json.dumps([(r.observation_id, r.payload_sha256, labels[r.target]) for r in training], separators=(",", ":")).encode()).hexdigest()
        if fingerprint != model.training_sha256 or len(training) != model.train_count:
            raise ValueError("Model training fingerprint does not match this pool")
    saved = list(csv.DictReader((results / "predictions.csv").open(encoding="utf-8", newline="")))
    indexed = {(r["policy"], r["agent_id"], r["target_id"]): r for r in saved}
    train_labels = [labels[t] for t, obs in by_target.items() if obs["rgb"].split == "train"]
    prior = (sum(train_labels) + 1) / (len(train_labels) + 2)
    rows, feature_drift = [], defaultdict(list)
    maximum_prediction_difference = 0.0
    for i, (target, observations) in enumerate(sorted(by_target.items(), key=lambda v: v[0].id), 1):
        if set(observations) != {"rgb", "thermal"}:
            raise ValueError("Missing or unexpected modality")
        reference = annotations[target.id]
        mask_path = pool._local_path(reference["mask_path"])
        if digest(mask_path) != reference["mask_sha256"]:
            raise ValueError("Reference mask SHA256 mismatch")
        with Image.open(mask_path) as source:
            mask = np.asarray(source)
            if source.format != "PNG" or source.mode != "L" or not set(np.unique(mask)) <= {0, 1, 2, 3, 4}:
                raise ValueError("Unexpected annotation format/classes")
            shape = source.size
        survivor = mask == 4
        label = int(survivor.any())
        if label != labels[target]:
            raise ValueError("Binary label differs from original mask")
        classes, counts = np.unique(mask, return_counts=True)
        if {str(int(c)): int(n) for c, n in zip(classes, counts)} != reference["class_pixels"]:
            raise ValueError("Stored mask class counts differ from original pixels")
        row = {"target_id": target.id, "sequence_id": observations["rgb"].sequence_id,
               "tick": observations["rgb"].tick, "split": observations["rgb"].split, "label": label,
               "survivor_pixels": int(survivor.sum()), "survivor_fraction": float(survivor.mean()),
               "mask_path": str(mask_path), "always_no": 0.0, "training_prior": prior}
        for modality, record in observations.items():
            if record.frame != observations["rgb"].frame or record.split != row["split"]:
                raise ValueError("Pairing/frame mismatch")
            observation = load_observation(pool, record)  # Verifies original payload SHA256.
            row[modality] = models[modality].predict(observation.payload)
            row[modality + "_path"] = observation.payload.path
            row[modality + "_correct"] = int(row[modality] >= 0.5) == label
            values = np.array(image_features(observation.payload, modality))
            standardized = (values - np.array(models[modality].center)) / np.array(models[modality].scale)
            feature_drift[modality, row["split"]].append(standardized)
            with Image.open(observation.payload.path) as source:
                if source.size != shape or source.mode != ("RGB" if modality == "rgb" else "L"):
                    raise ValueError("Image dimensions/mode mismatch")
                pixels = np.asarray(source)
                row[modality + "_mean"] = float(pixels.mean() / 255)
                row[modality + "_zero_fraction"] = float(np.mean(pixels == 0))
        row["fusion"] = (row["rgb"] + row["thermal"]) / 2
        row["fusion_correct"] = int(row["fusion"] >= 0.5) == label
        if row["split"] == "test":
            for key, policy, agent in (("rgb", "no_acquisition", "rgb-01"), ("thermal", "no_acquisition", "thermal-01"), ("fusion", "always_acquire", "rgb-01")):
                existing = indexed[policy, agent, target.id]
                if int(existing["reference_label"]) != label:
                    raise ValueError("Saved prediction reference differs from mask")
                maximum_prediction_difference = max(maximum_prediction_difference, abs(row[key] - float(existing["probability_after"])))
            row["rgb_uncertain_probability"] = float(indexed["uncertainty_threshold", "rgb-01", target.id]["probability_after"])
            row["rgb_uncertain_transfers"] = int(indexed["uncertainty_threshold", "rgb-01", target.id]["transfers"])
        else:
            row["rgb_uncertain_probability"], row["rgb_uncertain_transfers"] = None, None
        rows.append(row)
        if i % 50 == 0:
            print(f"Audited {i}/{len(by_target)} frames (frozen models, no fitting)", flush=True)
    if maximum_prediction_difference > 1e-12:
        raise ValueError("Frozen-model predictions do not reproduce experiment outputs")
    split_scores = {split: {m: scores([r for r in rows if r["split"] == split], m)
                            for m in ("rgb", "thermal", "fusion", "always_no", "training_prior")}
                    for split in ("train", "validation", "test")}
    sequence_scores = {sequence: {"split": selected[0]["split"],
                                  "metrics": {m: scores(selected, m) for m in ("rgb", "thermal", "fusion")}}
                       for sequence in sorted({r["sequence_id"] for r in rows})
                       if (selected := [r for r in rows if r["sequence_id"] == sequence])}
    test = [r for r in rows if r["split"] == "test"]
    complement = Counter()
    for row in test:
        rgb, thermal, fusion = [row[m + "_correct"] for m in ("rgb", "thermal", "fusion")]
        category = "both_correct" if rgb and thermal else "rgb_only_correct" if rgb else "thermal_only_correct" if thermal else "both_wrong"
        complement[category] += 1
        complement[f"{category}_label_{row['label']}"] += 1
        if fusion != thermal:
            complement["fusion_repairs_thermal" if fusion else "fusion_damages_thermal"] += 1
    positive_sizes = {}
    for split in split_scores:
        sizes = [r["survivor_fraction"] for r in rows if r["split"] == split and r["label"]]
        positive_sizes[split] = {"n": len(sizes), "min": min(sizes) if sizes else None,
                                  "median": float(np.median(sizes)) if sizes else None,
                                  "max": max(sizes) if sizes else None}
    drift = {m: {split: {"mean_abs_standardized_feature_mean": float(np.mean(np.abs(np.mean(feature_drift[m, split], axis=0)))),
                         "fraction_feature_values_outside_3_train_std": float(np.mean(np.abs(feature_drift[m, split]) > 3))}
                 for split in split_scores} for m in models}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "frames.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    chosen = gallery(rows, output)
    overview(rows, output)
    summary = {
        "scope": "frozen models and fixed 0.5 threshold; no training, calibration or test-based model selection",
        "pool_fingerprint": pool.fingerprint, "input_sha256": before,
        "integrity": {"image_observations_verified": len(pool.records), "mask_references_verified": len(annotations),
                      "binary_labels_match_masks": True, "class_pixel_counts_match_masks": True,
                      "group_overlap_between_splits": {f"{a}/{b}": sorted(groups[a] & groups[b]) for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))},
                      "max_abs_difference_from_saved_test_predictions": maximum_prediction_difference},
        "split_metrics": split_scores, "sequence_metrics": sequence_scores,
        "complementarity_test": dict(complement), "positive_object_area": positive_sizes,
        "feature_shift_diagnostics": drift, "gallery_targets": chosen,
        "frozen_models": [{"modality": m.modality, "version": m.version, "train_count": m.train_count,
                           "feature_count": len(m.coefficients), "initial_training_log_loss": m.initial_log_loss,
                           "final_training_log_loss": m.final_log_loss} for m in models.values()],
        "annotation_review_flags": [{"target_id": r["target_id"], "split": r["split"],
                                     "survivor_pixels": r["survivor_pixels"],
                                     "reason": "single Survivor pixel; semantic review needed, label unchanged"}
                                    for r in rows if r["survivor_pixels"] == 1],
    }
    if any(digest(p) != before[str(p)] for p in sources):
        raise ValueError("Audit input changed during execution")
    summary["integrity"]["input_metadata_and_results_unchanged"] = True
    summary["audit_script_sha256"] = digest(Path(__file__))
    write_json(output / "audit.json", summary)
    write_report(summary, rows, output)
    print(json.dumps({"split_metrics": {s: {m: {k: v for k, v in values.items() if k in ("accuracy", "recall", "auc", "brier", "positive_predictions")} for m, values in values.items()} for s, values in split_scores.items()},
                      "complementarity_test": dict(complement), "object_area": positive_sizes,
                      "gallery_cases": len(chosen)}, indent=2), flush=True)
    return summary


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=Path(r"D:\Doktorat\Platforma\data\pst900\pool"))
    parser.add_argument("--results", type=Path, default=Path("runs/pst900/results"))
    parser.add_argument("--output", type=Path, default=Path("runs/pst900/audit"))
    args = parser.parse_args()
    run(args.pool.resolve(), args.results.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
