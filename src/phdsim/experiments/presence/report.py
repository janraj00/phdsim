"""Render the fixed learning experiment results; no fitting or replay."""

def write_report(output, plan, rows):
    metric = rows[0].get('gain_metric', 'brier')
    objective = ('zmniejszanie liczby błędnych rozpoznań przy progu 0,5'
                 if metric == 'classification_error' else 'zmniejszanie błędu Brier')
    indexed = {(r['fusion'], r['policy']): r for r in rows}
    own = indexed['mean_probability', 'no_acquisition']
    mean = indexed['mean_probability', 'always_acquire']
    learned = indexed['learned_probability', 'always_acquire']
    selected = next((r for r in rows if r['fusion'] == 'mean_probability' and r['method'] == 'learned_gain'
                     and r['transfer_penalty'] == 0), None)
    lines = ['# Uczona fuzja i selektywna akwizycja', '',
             'Zadanie: obecność Survivor w całej klatce PST900. Agenci otrzymują RGB i thermal tej samej sceny i chwili.', '',
             f'Cel uczenia akwizycji: **{objective}** (`{metric}`).', '',
             f'Podział po rodzinach nagrań: {plan["frames"]["cnn_train"]} par CNN train, '
             f'{plan["frames"]["cnn_validation"]} CNN validation, {plan["frames"]["meta_train"]} meta train, '
             f'{plan["frames"]["test"]} test. Meta train jest wyłączone z uczenia i wyboru wag CNN.', '',
             'Obie metody fuzji i wszystkie strategie używają tych samych nowych sieci oraz przydziału. '
             'Poprzednie CNN były uczone na większej części danych, więc ich wyniki nie są bezpośrednim punktem porównania.', '',
             '## Odczyt tego przebiegu', '',
             f'Bez komunikacji trafność wynosi {own["accuracy"]:.1%}, przy zawsze pobieranej średniej {mean["accuracy"]:.1%}, '
             f'a przy zawsze pobieranej uczonej fuzji {learned["accuracy"]:.1%}. Uczona fuzja nie pokazała tu przewagi.', '',
             *(([f'Uczona akwizycja z cechami obrazu i zerową karą transferu, przy fuzji średniej: '
                 f'{selected["accuracy"]:.1%}, Brier {selected["brier"]:.4f}, {selected["transfers"]} transferów '
                 f'i {selected["bytes"] / 1_000_000:.2f} MB. Bez komunikacji Brier wynosi {own["brier"]:.4f}. '
                 f'Zmiana trafności względem własnych obserwacji: {(selected["accuracy"] - own["accuracy"]) * 100:+.2f} punktu procentowego.', '',
                 f'Kierunki wybranych transferów: RGB pobrał thermal {selected["rgb_to_thermal_pulls"]} razy, '
                 f'thermal pobrał RGB {selected["thermal_to_rgb_pulls"]} razy. '
                 'Sama asymetria transferów nie dowodzi trafnego wyboru konkretnych scen.', '']) if selected else []),
             '## Co jest uczone', '',
             '- Fuzja: regresja logistyczna na logitach RGB/thermal, ich iloczynie i różnicy. Stała regularyzacja ustalona przed testem.',
             ('- Akwizycja: regresja oczekiwanej zmiany poprawności odpowiedzi: +1 naprawa, -1 pogorszenie, 0 bez zmiany. '
              'Własny i połączony wynik są progowane przy 0,5.' if metric == 'classification_error' else
              '- Akwizycja: regresja przewidywanej poprawy Brier po transferze. Zyski ujemne też są uczone.'),
             '- Wersja confidence korzysta z własnego prawdopodobieństwa, jego kwadratu i entropii. Wersja quality dodaje osiem cech własnego obrazu: jasność, kontrast, udział ciemnych/jasnych pikseli, gradienty i jasność górnej/dolnej połowy.',
             '- Zewnętrzna walidacja pozostawia całą rodzinę nagrań. Wewnątrz każdej części uczącej osobne modele fuzji generują cele bez danej rodziny. Regularyzację akwizycji wybiera średni błąd po rodzinach.',
             f'- Po uczeniu: pobierz, gdy przewidywany spadek straty `{metric}` przewyższa karę za transfer oraz opcjonalnie za MB. '
             'Przy celu classification_error kara jest wyrażona w jednostkach oczekiwanej poprawy poprawności; przy Brier w jednostkach Brier.', '',
             'Decyzja nie widzi etykiety, maski, obrazu ani przewidywania sąsiada przed pobraniem. '
             'Identyfikator sceny nie jest uczoną cechą. Każdy agent ma jedną własną modalność, a po pobraniu uruchamia model drugiej modalności.', '',
             '## Wyniki wszystkich ustalonych wariantów', '',
             f'Trafność i Brier to średnie po {rows[0]["agent_frames"]} decyzjach agent–klatka; dwa kierunki transferu są liczone oddzielnie. '
             'Losowe pobieranie ma trzy ziarna dla każdej częstości. Liczba pobrań może się między metodami różnić; '
             'porównujemy krzywe jakości względem faktycznego kosztu, a nie tylko jeden wynik.', '',
             '| Fuzja | Strategia | Trafność | Brier ↓ | Transfery | MB |',
             '| --- | --- | ---: | ---: | ---: | ---: |']
    for row in rows:
        lines.append(f'| {row["fusion"]} | {row["policy"]} | {row["accuracy"]:.1%} | {row["brier"]:.4f} | {row["transfers"]} | {row["bytes"] / 1_000_000:.2f} |')
    lines += ['', '## Zakres wniosków', '',
              f'To diagnostyczny pilotaż na wcześniej oglądanym teście. {plan["frames"]["meta_train"]} par meta pochodzi z '
              f'{len(plan["recording_families"]["meta_train"])} rodzin nagrań; '
              'sąsiednie klatki nie stanowią niezależnych prób. Uczona fuzja ani akwizycja nie mają gwarantowanej przewagi.', '',
              'Koszt obejmuje oryginalny PNG: transfer i bajty. Przetwarzanie, narzut protokołu i fizyczny czas sieci są poza pomiarem. '
              'Nie wnioskujemy stąd o przyspieszeniu względem wyników czasowych autorów PST900.', '',
              'Pliki: plan.json — role danych; learning_config.json — ustalona siatka porównań; frozen.json — wersje zamrożone przed testem; '
              '*/models/learning.json — wagi fuzji i akwizycji; */models/meta_samples.jsonl — offline przykłady uczące; '
              '*/results/predictions.csv — decyzje i wyniki per agent; comparison.csv — pełna tabela. '
              'Pełne ślady JSONL można włączyć przez --trace, domyślnie siatka ich nie zapisuje.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
