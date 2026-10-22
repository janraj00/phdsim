# Kandydaci: multiview / UAV / active acquisition (2026-10-21)

Uzupełnienie [przeglądu 25 datasetów](DATASET_REVIEW_2026-10-18.md). Poniższe pozycje NIE zostały jeszcze dołączone do historycznej tabeli i punktacji 25; wymagają osobnej oceny kryteriów. Wybór jest oparty na dokumentacji, bez pobierania danych i uruchamiania modeli.

## Zbiory do audytu

| Dataset | Real/sim | Źródła | Geometria i czas | Zadanie / etykiety | Dopasowanie do selective acquisition | Główne ograniczenie | Priorytet |
|---|---|---|---|---|---|---|---|
| [JB3D](https://jb3d-dataset.github.io/Multi-View-Stereo/) | Real, UAV | Wideo RGB, zdjęcia RGB/T, LiDAR GT | Trajektorie i camera pose per-frame, wspólne ECEF/ENU | MVS, NVS, LiDAR reference | Next-best-view, selekcja klatek/widoków, koszt ruchu przy znanej trajektorii | Nie jest gotowym benchmarkiem detekcji; RGB/T nie muszą być współczasowe i pixel-aligned | A – geometria |
| [CoPerception-UAV](https://siheng-chen.github.io/dataset/coperception-uav/) | Sim, 5 UAV | RGB ze zsynchronizowanych agentów | Wspólne formacje, trzy wysokości | Detekcja 2D/3D, maski semantyczne, BEV | Wybór agenta, peer-query, overlap, zasłonięcia | Syntetyczny; dostęp full przez Baidu, sample przez Google Drive | A – multi-agent |
| [UAV3D](https://github.com/huiyegit/UAV3D) | Sim, UAV | Wielowidokowe sensory UAV | Sceny syntetyczne | 3D detection, tracking, collaborative perception | Wybór peer observations, skalowalność | Weryfikować konfigurację sensorów, dostępność i licencję danych | B |
| [U2UData](https://github.com/fengtt42/U2UData) | Sim, 3 UAV | LiDAR, RGB, depth, metadane środowiskowe | Zsynchronizowane loty w U2USim | 3D detection i tracking, 3 klasy | Selekcja agentów/modalności, uczenie polityki przy różnej pogodzie | Bardzo duży zbiór; symulacja, a nie realny pobór energii | A – multi-agent |
| [V2U4Real](https://github.com/VjiaLi/V2U4Real) | Real, pojazd + UAV | Multi-camera RGB i multi-LiDAR | Dane czasowe oraz metadata YAML | 3D detection, tracking, współpraca | Realne cross-view ask/no-ask; porównania early/late/intermediate i bandwidth | Jeden UAV jako partner; wysokie koszty pipeline 3D CUDA/spconv | A – real heterogeneous |
| [AirV2X-Perception](https://github.com/taco-group/AirV2X-Perception) | Sim / sprawdzić szczegóły generowania | UAV + pojazd + infrastruktura, wielomodalne | Heterogeniczne widoki, ruchoma perspektywa UAV | 3D cooperative perception | Wybór platformy i widoku, wpływ położenia UAV | Należy zweryfikować rozmiar, synchroniczność, wersję danych i licencję | B |
| [UAV-AVL Benchmark](https://github.com/UAV-AVL/Benchmark) | Do weryfikacji | Obrazy UAV i referencje | Camera pose c2w/w2c, lokalne XYZ i attitude | Visual localization | Aktywny wybór kolejnego widoku dla lokalizacji | Inny task niż detekcja; audyt licencji i plików | B – alternatywny task |
| [VisDrone](https://github.com/VisDrone/VisDrone-Dataset) | Real, UAV | RGB obraz/wideo | Trajektorie/pozy nie są centralnym elementem standardowego benchmarku | 2D detection/tracking | Trening detektora bazowego i uncertainty; ograniczona ewaluacja ruchu | Brak standardowego pełnego action-space z kosztami | C – perception pretraining |

## Ważne rozróżnienia

- **Replay-based acquisition:** polityka wybiera spośród zarejestrowanych sensorów, agentów i pozycji. Dataset nie umożliwia prawdziwej obserwacji z dowolnego nowego punktu.
- **Acquisition costs:** dystans między zarejestrowanymi pozami można oszacować, ale to *proxy*, nie pomiar zużycia baterii. Byte budget zależy od faktycznego formatu wiadomości i kompresji, latency od protokołu i środowiska.
- **Geometria ≠ współpraca:** wiele kamer jednego UAV/auta nie oznacza wielu niezależnych agentów. Powtarzane przeloty nad statyczną sceną to pseudo-multi-agent, nie synchroniczne loty.
- **Modalność ≠ miejsce:** w V2U4Real drone/vehicle i wyposażenie sensorowe są powiązane z platformą. Ablacje muszą kontrolować ten confounder.
- **Ground truth:** JB3D wspiera rekonstrukcję/depth z LiDAR, ale wymaga dodatkowych etykiet, jeśli chcemy liczyć object mAP/mIoU.
- **Split:** wg scen/lokalizacji/lotów, wszystkie widoki tego samego obiektu lub sceny w tej samej partycji.

## Następne testy

1. JB3D: jeden krótki segment wideo + pozy + LiDAR; sprawdzić możliwość utworzenia katalogu akcji i metryki reconstruction-quality vs liczba widoków/czas/dystans.
2. CoPerception-UAV: sample, sprawdzić ID agentów, wspólną geometrię, annotations i policzyć single vs all vs selected peers.
3. V2U4Real: sprawdzić jedną sekwencję z parą vehicle/UAV i istniejącymi checkpointami; sprawdzić osobno wpływ widoku i modalności.
4. U2UData: minimalna paczka zamiast pełnych setek tysięcy klatek.
5. Rozszerzyć schemat katalogu o: `acquisition_mode`, `camera_pose`, `synchronized_agents`, `candidate_action_set`, `cost_proxy`, `measured_cost`, `labels_task`, `download_verified`, `license_verified`.

## Źródła
- JB3D dataset: https://zenodo.org/records/22787920 ; paper DOI https://doi.org/10.1016/j.ophoto.2026.100149 ; licencja danych CC BY 4.0 (oficjalna strona)
- CoPerception-UAV: https://siheng-chen.github.io/dataset/coperception-uav/
- UAV3D: https://github.com/huiyegit/UAV3D
- U2UData: https://arxiv.org/abs/2408.00606
- V2U4Real CVPR 2026: https://arxiv.org/abs/2603.25275
- AirV2X: https://arxiv.org/abs/2506.19283
- UAV-AVL: https://github.com/UAV-AVL/Benchmark
- VisDrone: https://github.com/VisDrone/VisDrone-Dataset
