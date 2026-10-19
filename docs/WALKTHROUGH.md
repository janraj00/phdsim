# Symulacja krok po kroku z kodem

Zacznij od [wykonanego śladu](../runs/walkthrough/20261018_code_review/walkthrough.md).
Zawiera pięć scenariuszy i 130 zarejestrowanych wywołań/zdarzeń. Każdy link
prowadzi do pliku oraz linii funkcji, która rzeczywiście została wywołana.
Przy funkcji widzisz krótkie objaśnienie i podsumowanie zwróconych danych.

Wiersze pokazują kolejność **wejścia** do funkcji. Strzałki oznaczają
zagnieżdżenie; podsumowanie wartości zwracanej zostało dopisane po powrocie.
To pomaga odróżnić „uruchom silnik” od operacji, które silnik wykonuje w środku.

## Jak uruchomić i czytać przykład

Z głównego katalogu projektu:

```powershell
.\scripts\walkthrough.ps1

# Tylko jeden z przepływów:
.\scripts\walkthrough.ps1 -Workflow pstnet
.\scripts\walkthrough.ps1 -Workflow presence

# Jawny nowy katalog wyjściowy:
.\scripts\walkthrough.ps1 -Output runs\walkthrough\moja_proba
```

Domyślny katalog ma znacznik czasu. Istniejący katalog nie jest nadpisywany.
Powstają `walkthrough.md`, `steps.json` i syntetyczne wejścia dla demonstracji
PSTNet. Numery linii są odczytywane podczas wykonania; po kolejnych zmianach
kodu uruchom przykład ponownie, żeby odświeżyć linki.

Przykład PSTNet wykonuje prawdziwy runtime i oryginalne architektury na
syntetycznej klatce z losowymi wagami. Pokazuje dwie jawnie wybrane gałęzie;
nie służy do oceny jakości sieci. Nie potrzebuje checkpointów ani pobierania.
Przykład presence odczytuje istniejącą pulę, harmonogram i wytrenowane modele
z domyślnych lokalizacji na tej maszynie. Bierze tylko pierwszą klatkę testową.

Kod narzędzia jest w [walkthrough/](../src/phdsim/walkthrough/). Używa profilera
Pythona do przechwycenia wybranych wywołań i istniejących zdarzeń runtime.
Nie dopisuje wywołań treningu ani logowania do klas modeli.

## Aktualny główny przepływ: PSTNet

Najpierw przejdź w śladzie przez **„PSTNet: koniec po RGB”**, potem przez
**„PSTNet: pobranie thermal”**. W obu przypadkach RGB wykonuje się jeden raz.
Różnica zaczyna się po decyzji o pobraniu.

Przy zwykłym uruchomieniu eksperymentu ścieżka wejściowa wygląda tak:

```text
phdsim pstnet run
  cli.main()
    cli.pstnet.main()
      experiments.pstnet.replay.run_gated()
        load_models() + kontrola wersji modeli i danych
        load_frames(verify=False) + kontrola pełnego splitu
        utworzenie LearnedPstPolicy i SegmentationReplay
        pętla po klatkach testowych
          SegmentationReplay.predict(frame)
          odczyt referencyjnej maski i ocena poza polityką
        zapis raportu
```

Demo zaczyna od gotowych instancji sieci i pojedynczej klatki. Właściwy
protokół `run_gated()` wymaga checkpointów RGB, fuzji i modelu akwizycji oraz
pełnego splitu benchmarku. Dostępność tych elementów opisuje
[stan eksperymentów](EXPERIMENTS.md).

| Kolejność | Otwórz w kodzie | Co sprawdzić |
| ---: | --- | --- |
| 1 | [cli.main()](../src/phdsim/cli/__init__.py) i [cli.pstnet.main()](../src/phdsim/cli/pstnet.py) | Wybór workflow i akcji; CLI przekazuje argumenty do protokołu. |
| 2 | [run_gated()](../src/phdsim/experiments/pstnet/replay.py) | Odczyt wag, sprawdzenie pochodzenia gate i danych, utworzenie silnika. |
| 3 | [load_frames()](../src/phdsim/datasets/pst900/segmentation.py) | `verify=False` parsuje metadane. Nie otwiera z góry thermal ani referencji. |
| 4 | [SegmentationReplay.predict()](../src/phdsim/runtime/segmentation.py) | Główna funkcja pojedynczej klatki. To najlepszy punkt do rozpoczęcia debugowania. |
| 5 | [rgb_tensor()](../src/phdsim/perception/pstnet/input.py) | SHA256, odczyt PNG i przeskalowanie do tensora `1×3×360×640`; wartości w `[0,1]`. |
| 6 | [PstRgb.forward()](../src/phdsim/perception/pstnet/rgb.py) | Enkoder ResNet-18 i dekoder tworzą `1×5×360×640` logitów. |
| 7 | [rgb_features()](../src/phdsim/perception/pstnet/features.py) | Z obrazu RGB i jego logitów powstaje 19 cech; `argmax` daje lokalną maskę. |
| 8 | [RgbAcquisitionView](../src/phdsim/decision/pstnet/view.py) | Widok zawiera tylko te cechy oraz rozmiar transferu thermal. |
| 9 | [LearnedPstPolicy.acquire()](../src/phdsim/decision/pstnet/learned.py) | Przewidywany zysk porównywany jest z kosztem. Demo używa [FixedPstPolicy](../src/phdsim/decision/pstnet/fixed.py), aby pokazać obie odpowiedzi. |
| 10 | [thermal_tensor()](../src/phdsim/perception/pstnet/input.py) | Ta funkcja pojawia się dopiero w gałęzi z pobraniem. Odczytuje thermal i uzupełnia zera przez inpainting. |
| 11 | [PstFusion.forward()](../src/phdsim/fusion/pstnet/model.py) | Dostaje już policzone `rgb_logits`, więc pomija ponowne liczenie RGB. Łączy 5 kanałów confidence, thermal i 3 kanały RGB. |
| 12 | [SegmentationPrediction](../src/phdsim/runtime/segmentation_result.py) | Wynik runtime: maska RGB, maska końcowa, decyzja, bajty i czasy etapów. |
| 13 | [reference_mask()](../src/phdsim/perception/pstnet/input.py) i [confusion_matrix()](../src/phdsim/evaluation/segmentation.py) | Referencja jest odczytywana po predykcji. Nie jest wejściem decyzji. |

W `predict()` zatrzymaj się przy `if acquired:`. Przy `False` maska końcowa
pozostaje maską RGB. Przy `True` wykonuje się odczyt thermal i fuzja, po czym
końcowa maska pochodzi z połączonego wyniku. W śladzie widać tę różnicę bez
przeszukiwania całej hierarchii warstw PyTorch.

## Wcześniejszy przepływ: presence, wielu agentów

Tutaj każdy agent odpowiada, czy w całym kadrze jest Survivor. Modele zwracają
po jednym prawdopodobieństwie. Zwykły protokół przechodzi przez:

```text
phdsim presence run
  cli.presence.main()
    ObservationPool + Schedule.load() + load_cnn()
    experiments.presence.replay.run_replay()
      konfiguracja fuzji, oceny, strategii i budżetu
      ReplayEngine.run() dla każdej strategii
        własne obserwacje agentów w bieżącej klatce
        percepcja -> widok decyzji -> choose_action()
        Stop albo koszt -> dostarczenie peer image -> percepcja -> fuzja
        ocena i logi
      predictions.csv + summary.json + raport
```

W wygenerowanym śladzie porównaj strategie `no_acquisition`, `always_acquire`
i `uncertainty_threshold`. Używają tej samej klatki i tych samych wag. W każdej
strategii uruchamiana jest nowa instancja percepcji z pustym cache.

| Otwórz w kodzie | Na co patrzeć |
| --- | --- |
| [run_replay()](../src/phdsim/experiments/presence/replay.py) | Składanie protokołu oraz pętla po politykach. |
| [ReplayEngine.run()](../src/phdsim/runtime/presence.py) | Dwie pętle: po klatkach i po agentach; wewnątrz pętla kolejnych decyzji. |
| [load_observation()](../src/phdsim/perception/baseline.py) | Wirtualne dostarczenie PNG i sprawdzenie jego bajtów. |
| [CnnPerception.process()](../src/phdsim/perception/cnn_perception.py) | Wybór modelu modalności i cache po SHA256. Ponowne `process()` nie zawsze oznacza ponowny `forward()`. |
| [DecisionView](../src/phdsim/decision/view.py) i [ActionEstimate](../src/phdsim/decision/actions.py) | Co widzi agent oraz jakie akcje silnik uznał za dostępne. |
| [choose_action()](../src/phdsim/decision/policy.py) i [policies/](../src/phdsim/decision/policies/) | Wybrana reguła oraz kontrola, czy zwróciła legalną akcję. |
| [CostLedger](../src/phdsim/costs/ledger.py) | Sprawdzenie budżetu przed akcją i rozliczenie po wykonaniu. |
| [MeanProbabilityFusion.update()](../src/phdsim/fusion/mean_probability.py) | Po drugim obrazie: średnia prawdopodobieństw i połączenie identyfikatorów dowodów. |
| [BrierEvaluator.evaluate()](../src/phdsim/evaluation/presence.py) | Ocena przed/po; trafia do logu, nie do widoku polityki. |

Silnik presence przygotowuje własne obserwacje wszystkich agentów na początku
klatki. Odbiorca uzyskuje obraz sąsiada dopiero przez `Acquire`. PSTNet ma osobny,
leniwy odczyt thermal już na poziomie pliku. W obu ścieżkach polityka nie widzi
niepozyskanego obrazu ani maski referencyjnej.

## Gdzie są teraz typy

| Odpowiedzialność | Typy i moduł |
| --- | --- |
| Wspólna tożsamość | `TargetRef`, `stable_id` w [core/identity.py](../src/phdsim/core/identity.py) |
| Dane dostarczone agentowi | `Observation`, `ObservationRef` w [datasets/observations.py](../src/phdsim/datasets/observations.py) |
| Wynik percepcji presence | `Prediction`, `PerceptionEvidence`, `TaskResult` w [perception/results.py](../src/phdsim/perception/results.py) |
| Wielkości kosztów | `CostStatus`, `CostComponent`, `CostVector` w [costs/types.py](../src/phdsim/costs/types.py) |
| Akcje i kandydaci | `Acquire`, `Stop`, `ActionEstimate` w [decision/actions.py](../src/phdsim/decision/actions.py) |
| Stan dostępny polityce presence | `DecisionView` w [decision/view.py](../src/phdsim/decision/view.py) |
| Stan dostępny polityce PSTNet | `RgbAcquisitionView` w [decision/pstnet/view.py](../src/phdsim/decision/pstnet/view.py) |
| Ocena offline | `QualityChange` w [evaluation/results.py](../src/phdsim/evaluation/results.py) |
| Wynik wykonania segmentacji | `SegmentationPrediction` w [runtime/segmentation_result.py](../src/phdsim/runtime/segmentation_result.py) |

Nowy typ dodawaj przy odpowiedzialności, której dotyczy. Typ obserwacji nie zna
polityki ani wyniku oceny; widok decyzji może używać dostarczonych obserwacji
i predykcji, ale nie referencji ewaluacyjnej. Typy puli i przydziału pozostają
w `datasets/pool.py` i `datasets/allocation.py`. Konfiguracje treningu są przy
odpowiednich trenerach. Nie ma wspólnego zbiorczego `records.py`.
