# Przegląd 25 datasetów dla PHDSIM

Stan przeglądu: 2026-10-18. Ocena dotyczy selektywnego pozyskiwania istniejących obserwacji i współpracy agentów. Osobno uwzględnia obecny pipeline segmentacji RGB/thermal na PST900.

## Rekomendacja

Kontynuować PST900 jako kontrolę działającej pętli. Jako następny rzeczywisty zbiór RGB-T sprawdzić małą paczkę Caltech. Dla właściwej współpracy źródeł wykonać audyt jednej sekwencji UrbanIng-V2X; jeżeli integracja 3D okaże się zbyt kosztowna, rozważyć prostszy układ dwóch pojazdów V2V4Real. Wybór spośród większej liczby sąsiadów jest zaletą UrbanIng. V2V4Real pozwala przede wszystkim badać, czy i kiedy pytać jednego sąsiada.

Krótka lista uzupełniająca: MUSES dla niepewności, The Great Outdoors dla realnych danych terenowych z wieloma sensorami, DeLiVER do sprawdzenia metod na opublikowanych wagach. Nie uruchamiać siedmiu pipeline’ów naraz: wybrać jeden kolejny rzeczywisty zbiór i ewentualnie jeden zbiór techniczny.

To wstępna kwalifikacja na podstawie dokumentacji, a punkty są jawną oceną projektową. Nie są zmierzoną skutecznością modeli ani prawdopodobieństwem powodzenia. Drobne różnice punktów nie uzasadniają wyboru bez pilota. Przegląd nie obejmował pobierania nowych surowych danych, uruchamiania checkpointów ani treningu.

## Co policzono w pierwotnej liście

CSV zawiera 25 zbiorów: 22 rzeczywiste i 3 syntetyczne. Pięć rzeczywistych pozycji jest oznaczonych jako współpracujące (Tier A), dwie symulowane jako A-sim, 15 jako B i 3 jako C. Aż 12 pozycji dostało pierwotnie 5/5; średnia Fit wynosi 4,36/5. Ta skala słabo wybiera kolejny eksperyment.

Wielomodalność, wiele kamer i wiele agentów są różnymi własnościami. Podział sensorów jednego robota między logicznych agentów jest poprawnym eksperymentem software’owym, ale nie odtwarza geometrii i zasłonięć między niezależnymi platformami. Zapisane dane umożliwiają ukrywanie i odsłanianie istniejących pomiarów. Nie umożliwiają obserwacji po dowolnym nowym ruchu robota.

## Kryteria i jawne wagi

Oceny 0–5; im wyżej, tym lepsze dopasowanie. Wszystkie składowe poniżej są osądem na podstawie opisanych cech. R i F są wstępne, ponieważ dostępność plików i inferencja nie zostały przetestowane.

| Kod | Znaczenie i kotwice skali | Badania | Następny pilot |
|---|---|---:|---:|
| C | Rozproszone źródła: 0 jeden robot; 3 pojazd + infrastruktura; 4 dwa mobilne pojazdy; 5 wiele wybieralnych węzłów | 30% | 0% |
| M | Różnorodność wyboru percepcji: 2 dwie główne rodziny; 3 trzy; 4 cztery; 5 pięć lub więcej. GNSS i pochodnych reprezentacji nie dodajemy jak nowych modalności percepcji | 15% | 0% |
| E | Dopasowanie etykiet do ewaluacji percepcji: 1 głównie trajektoria; 2 etykiety pośrednie; 4 boxy obiektów; 5 maski segmentacji | 15% | 30% |
| G | Czas i geometria: 1 numer klatki; 2 słaba struktura czasowa; 3 częściowa; 4 sekwencje i kalibracja; 5 bogate trajektorie/pozy | 15% | 0% |
| R | Dokumentacja, devkit i opublikowane baseline’y: 2 podstawowy loader; 3 narzędzia i protokół; 4 rozbudowany benchmark; 5 dojrzały ekosystem/opublikowane warianty wag | 10% | 20% |
| V | Realność pomiarów: 5 rzeczywiste; 1 syntetyczne | 15% | 0% |
| F | Łatwość wejścia z obecnej platformy: 1 duża zmiana; 2 nowa percepcja/fuzja; 3 ponowne użycie obrazu/segmentacji lub gotowych modeli; 5 adapter już działa | 0% | 35% |
| D | Bliskość zastosowania UAV/teren: 1 droga/symulacja drogowa; 2 przemysłowy AMR; 3 UGV; 4 teren off-road; 5 UAV w naturze | 0% | 15% |

Badania = (30C + 15M + 15E + 15G + 10R + 15V) / 5. Pilot = (30E + 20R + 35F + 15D) / 5. Skala 0–100. Pilot mierzy łatwość kontynuacji obecnej pracy, więc nie zastępuje oceny współpracy. „Badania” premiują istniejące etykiety segmentacji i realne dane zgodnie z obecnym zadaniem; przy przejściu do SLAM trzeba zmienić kryterium E i przeliczyć ranking.

## Wszystkie 25 pozycji

Kolejność według punktów Badania; remisy rozstrzygnięto punktami Pilot i nazwą wyłącznie dla uporządkowania tabeli.

| Dataset / źródło | Badania /100 | Pilot /100 | Dane | Wniosek |
|---|---:|---:|---|---|
| [UrbanIng-V2X](https://thi-ad.github.io/urbaning/) | 89 | 50 | realne | Krótka lista: główny cel współpracy rozproszonych źródeł |
| [V2V4Real](https://arxiv.org/abs/2303.07601) | 80 | 57 | realne | Krótka lista: prostsza realna współpraca mobilna |
| [OPV2V](https://arxiv.org/abs/2109.07644) | 76 | 61 | syntetyczne | Rezerwa symulacyjna: skalowanie liczby agentów |
| [V2XSet](https://github.com/DerrickXuNu/v2x-vit) | 74 | 57 | syntetyczne | Rezerwa symulacyjna: asynchronia i błąd pozy |
| [V2X-Seq](https://github.com/AIR-THU/DAIR-V2X-Seq) | 72 | 46 | realne | Rezerwa: polityka czasowa po uruchomieniu V2I |
| [TUMTraf-V2X](https://tum-traffic-dataset.github.io/tumtraf-v2x/) | 71 | 50 | realne | Rezerwa / alternatywa V2I z mocnymi baseline'ami |
| [DAIR-V2X](https://air.tsinghua.edu.cn/DAIR-V2X/english/index.html) | 68 | 57 | realne | Rezerwa: pierwszy realny V2I |
| [nuScenes](https://arxiv.org/abs/1903.11027) | 61 | 54 | realne | Odłożyć: duży benchmark referencyjny |
| [Seeing Through Fog](https://github.com/princeton-computational-imaging/SeeingThroughFog) | 60 | 53 | realne | Rezerwa: odporność na pogodę |
| [MUSES](https://github.com/timbroed/MUSES) | 59 | 63 | realne | Krótka lista: niepewność i wybór modalności |
| [Boreas](https://github.com/utiasASRL/pyboreas) | 59 | 50 | realne | Rezerwa: sezonowość i lokalizacja |
| [The Great Outdoors](https://unmannedlab.org/the-great-outdoors-dataset/) | 58 | 64 | realne | Krótka lista: realne multimodalne dane terenowe |
| [View of Delft](https://tudelft-iv.github.io/view-of-delft-dataset/) | 56 | 57 | realne | Rezerwa: kontrolowany eksperyment RGB/radar/LiDAR |
| [CMHT Autonomous](https://pmc.ncbi.nlm.nih.gov/articles/PMC12175244/) | 55 | 49 | realne | Rezerwa: RGB/T/radar/LiDAR dla detekcji |
| [SEW Multimodal AMR 2025](https://github.com/SEW-Eurodrive-Open-Source/Multimodal_AMR_dataset) | 55 | 45 | realne | Rezerwa: wiele modalności, duży koszt danych |
| [Caltech Aerial RGB-Thermal](https://github.com/aerorobotics/caltech-aerial-rgbt-dataset) | 54 | 78 | realne | Krótka lista: następny zbiór RGB-T / UAV |
| [RADIATE](https://pro.hw.ac.uk/radiate/) | 54 | 53 | realne | Rezerwa: radar w trudnej pogodzie |
| [M2DGR](https://github.com/SJTU-ViSYS/M2DGR) | 54 | 34 | realne | Odłożyć, chyba że wybieramy lokalizację |
| [A2D2](https://arxiv.org/abs/2004.06320) | 53 | 63 | realne | Rezerwa: wybór widoku i RGB/LiDAR |
| [RaDelft](https://github.com/RaDelft/RaDelft-Dataset) | 48 | 34 | realne | Odłożyć: wyspecjalizowane przetwarzanie radaru |
| [Oxford Radar RobotCar](https://oxford-robotics-institute.github.io/radar-robotcar-dataset/) | 48 | 28 | realne | Odłożyć do eksperymentu lokalizacyjnego |
| [KAIST Multispectral Pedestrian](https://github.com/SoonminHwang/rgbt-ped-detection) | 47 | 64 | realne | Odłożyć: klasyczny baseline RGB-T |
| [DeLiVER](https://github.com/InSAI-Lab/DELIVER) | 46 | 74 | syntetyczne | Krótka lista techniczna: gotowe modele selekcji modalności |
| [PST900](https://github.com/ShreyasSkandanS/pst900_thermal_rgb) | 45 | 86 | realne | Kontynuować obecny eksperyment kontrolny |
| [FLIR ADAS](https://oem.flir.com/en-150/solutions/automotive/adas-dataset-form/) | 45 | 60 | realne | Odłożyć: dodatkowy prosty RGB-T |

## Stabilność punktacji

Zmieniono kolejno każdą wagę o −25% i +25%, a następnie normalizowano sumę do 100%. Pozostałe oceny nie zmieniały się. Pozycje przy remisach są wspólne. To analiza wrażliwości na wagi, nie przedział ufności i nie test niepewności samych ocen.

| Najlepsze realne do badań | Punkty | Zakres miejsca wśród 22 realnych |
|---|---:|---|
| UrbanIng-V2X | 89 | 1–1 |
| V2V4Real | 80 | 2–2 |
| V2X-Seq | 72 | 3–3 |
| TUMTraf-V2X | 71 | 4–4 |
| DAIR-V2X | 68 | 5–5 |

| Najłatwiejsze do następnego pilota | Punkty | Zakres miejsca wśród 25 |
|---|---:|---|
| PST900 | 86 | 1–1 |
| Caltech Aerial RGB-Thermal | 78 | 2–2 |
| DeLiVER | 74 | 3–3 |
| The Great Outdoors | 64 | 4–7 |
| KAIST Multispectral Pedestrian | 64 | 4–7 |

Wysoka pozycja PST900 w pilocie wynika z działającego adaptera i ponownego użycia kodu. Nie jest argumentem za używaniem go jako głównego dowodu współpracy. Wynik Caltech obejmuje dopasowanie do UAV, ale nadal wymaga audytu etykiet i geometrii. Zmiana pojedynczej składowej o 1 punkt zmienia wynik Badania o maksymalnie 6 punktów, a Pilot o maksymalnie 7 punktów.

## Weryfikacja poszczególnych zbiorów

### Caltech Aerial RGB-Thermal

RGB, thermal, GPS i IMU; segmentacja 10 ocenianych klas. Paczka labeled_rgbt_pairs.zip ma 4,3 GB. Osobne dane thermal-only nie są dodatkowymi kompletnymi parami.

Maski opisano jako anotacje obrazu thermal. Trzeba sprawdzić wspólną płaszczyznę RGB/T i podział po trajektoriach. Kalibracja i rektyfikacja nie gwarantują zgodności piksel w piksel.

Źródła: [1](https://github.com/aerorobotics/caltech-aerial-rgbt-dataset), [2](https://data.caltech.edu/records/cks6g-ps927), [3](https://arxiv.org/html/2403.08997v2).

### M2DGR

Wiele kamer, IR, event, LiDAR, IMU/GNSS i referencyjne trajektorie; 36 sekwencji, około 1 TB.

Bardzo bogate sensory, ale zadaniem referencyjnym jest SLAM. Przejście z obecnej segmentacji wymaga nowej percepcji, fuzji i metryki błędu pozy.

Źródła: [1](https://github.com/SJTU-ViSYS/M2DGR).

### The Great Outdoors

RGB, LWIR, LiDAR, radar i nawigacja; semantyka terenu. Obecna strona udostępnia osobne paczki segmentacji RGB/LWIR i 17 surowych trajektorii.

W części danych z 2024 r. zgłoszono utratę danych LiDAR. Wspólny zbiór kompletnych, oznaczonych obserwacji wymaga audytu. Jeden robot.

Źródła: [1](https://unmannedlab.org/the-great-outdoors-dataset/), [2](https://unmannedlab.org/the-great-outdoors-dataset/download/).

### SEW Multimodal AMR 2025

Aktualna dokumentacja opisuje wydanie 2026: 15 921 klatek kluczowych, sensory RGB/T, radar, ToF/NIR, laser 2D i ultradźwięki. Główna paczka 78 GB / 162 GB po rozpakowaniu.

Zmiana z segmentacji na detekcję; etykiety testowe ukryte. Preview 20 GB / 39 GB. To jeden AMR, a wiele scen zainscenizowano.

Źródła: [1](https://github.com/SEW-Eurodrive-Open-Source/Multimodal_AMR_dataset).

### CMHT Autonomous

Ponad 9000 klatek, cztery rodziny sensorów percepcyjnych, GPS/IMU, ROS2 i tracklety 3D. Udostępniono skrypty projekcji.

Wspólne pole widzenia sensorów ograniczone do przodu pojazdu; mało pieszych. Etykiety kamer wymagają projekcji etykiet 3D. Brak współpracujących pojazdów.

Źródła: [1](https://pmc.ncbi.nlm.nih.gov/articles/PMC12175244/), [2](https://pubmed.ncbi.nlm.nih.gov/40534724/).

### MUSES

2500 scen z kamerą RGB, LiDAR, radarem i event; segmentacja semantyczna/panoptyczna oraz etykiety niepewności. Nowy adres pobierania: muses.ethz.ch.

Brak thermal i wielu agentów. Etykiety testowe ukryte; lokalny eksperyment wymaga zachowania osobnego holdoutu. Inny model fuzji niż PSTNet.

Źródła: [1](https://github.com/timbroed/MUSES), [2](https://muses.ethz.ch/).

### Seeing Through Fog

12 000 próbek drogowych i 1500 pomiarów z komory mgłowej. Sensory obejmują pasma widzialne, mmWave, NIR i FIR; etykiety detekcji 2D/3D.

Dostęp, kompletność wspólnych modalności i starszy pipeline wymagają osobnego uruchomienia. To badanie wyboru sensora na jednej platformie.

Źródła: [1](https://github.com/princeton-computational-imaging/SeeingThroughFog), [2](https://light.princeton.edu/datasets/automated_driving_dataset/).

### View of Delft

8600 klatek; kalibrowane kamera stereo, radar 3+1D, LiDAR i odometria. Etykiety 3D z identyfikatorami obiektów.

Dostęp na wniosek, nowa procedura od sierpnia 2026. Brak thermal i współpracowników; potrzebna detekcja 3D.

Źródła: [1](https://tudelft-iv.github.io/view-of-delft-dataset/).

### nuScenes

1000 scen po 20 s, 6 kamer, 5 radarów i LiDAR. Dojrzały devkit i detekcja/tracking 3D.

Kamery wokół jednego pojazdu nie są osobnymi mobilnymi agentami. Duży koszt danych i percepcji względem małego pilota.

Źródła: [1](https://arxiv.org/abs/1903.11027), [2](https://github.com/nutonomy/nuscenes-devkit).

### Oxford Radar RobotCar

Rozszerzenie RobotCar o radar FMCW i dwa LiDAR-y, z referencyjną odometrią radarową dla 280 km przejazdów.

Brakuje etykiet zgodnych z obecną segmentacją. Powtarzane trasy to dane jednego pojazdu z różnych przejazdów, a nie jednoczesna współpraca agentów.

Źródła: [1](https://oxford-robotics-institute.github.io/radar-robotcar-dataset/).

### Boreas

RGB, LiDAR 128, radar, GNSS i pozy. Aktualny devkit obsługuje także detekcję 3D obok odometrii/lokalizacji.

Pomiary sensorów są asynchroniczne; dokładne timestampy i pozy wymagają kompensacji czasu/ruchu. Nie zakładać par po indeksie.

Źródła: [1](https://github.com/utiasASRL/pyboreas).

### RADIATE

Około 3 h oznaczonych obrazów radaru i ponad 200 tys. instancji; kamera, LiDAR i GPS/IMU, mgła i śnieg.

Ocena jest radarocentryczna; nie utożsamiać etykiet w przestrzeni radaru z maską RGB. Jeden pojazd.

Źródła: [1](https://pro.hw.ac.uk/radiate/).

### RaDelft

Radar na kilku poziomach przetwarzania, kamera, LiDAR i odometria. Aktualne cztery klasy etykiet punktowych generowane automatycznie.

Dostęp na wniosek; pseudoetykiety zależne od innej modalności wymagają kontroli oceny. Nie traktować różnych reprezentacji radaru jako niezależnych sensorów.

Źródła: [1](https://github.com/RaDelft/RaDelft-Dataset).

### A2D2

6 kamer, 5 LiDAR-ów; 41 277 klatek z semantyką, w tym 12 497 z boxami 3D. Surowe sekwencje i etykiety mają różną gęstość.

Oznaczone klatki są niesekwencyjne. Niezależne kamery na jednym aucie nie wystarczają do badania mobilnej współpracy.

Źródła: [1](https://arxiv.org/abs/2004.06320), [2](https://a2d2-dataset.github.io/).

### DeLiVER

Dane syntetyczne RGB, depth, event i LiDAR; segmentacja, awarie sensorów, gotowe wagi CMNeXt. Publiczna paczka front-view około 12,2 GB.

Opis sześciu widoków w projekcie nie oznacza, że wszystkie są w paczce front-view. Modele każdej kombinacji są osobno trenowane; porównanie ich wyników nie izoluje samego pozyskania.

Źródła: [1](https://github.com/InSAI-Lab/DELIVER), [2](https://huggingface.co/datasets/InSAI-Lab/DELIVER).

### FLIR ADAS

Obecna strona opisuje rozszerzone wydanie z 26 442 oznaczonymi klatkami łącznie. Część wideo ma 7498 klatek z dopasowaniem RGB/T 1:1.

26 442 to nie liczba par. Trzeba przypiąć wersję, parowanie i geometrię. Pobranie wymaga konta; zadaniem jest detekcja.

Źródła: [1](https://oem.flir.com/en-150/solutions/automotive/adas-dataset-form/).

### KAIST Multispectral Pedestrian

Około 95 tys. par RGB/T 640×480 przy 20 Hz, dzień i noc, korespondencje czasowe obiektów.

Jeden rodzaj zadania i dwie modalności. Oficjalne repo ostrzega przed różnymi ustawieniami ewaluacji; trzeba przypiąć anotacje i protokół.

Źródła: [1](https://github.com/SoonminHwang/rgbt-ped-detection).

### PST900

RGB-T i maski segmentacji już zintegrowane. Lokalny audyt: 885 kompletnych trójek, podczas gdy publikacja i repo podają 894.

Brak realnej współpracy różnych platform; geometria i sekwencyjność ograniczone. Oficjalne depth jest pochodną stereo, a nie dodatkowym niezależnym czujnikiem. Wagi autorów lokalnie nadal niedostępne.

Źródła: [1](https://github.com/ShreyasSkandanS/pst900_thermal_rgb). Stan lokalny: [audyt danych](DATA.md) i [status eksperymentów](EXPERIMENTS.md).

### DAIR-V2X

Realne dane pojazdu i infrastruktury z kamerami/LiDAR-em. Cała rodzina DAIR-V2X ma 72 890 klatek LiDAR i tyle samo obrazów.

Liczby całej rodziny nie oznaczają tylu par współpracujących chwil. Należy używać części C, metadanych parowania i ustalonego wspólnego obszaru oceny.

Źródła: [1](https://air.tsinghua.edu.cn/DAIR-V2X/english/index.html), [2](https://github.com/AIR-THU/DAIR-V2X).

### V2X-Seq

Sequential Perception Dataset ma ponad 15 tys. klatek z 95 scenariuszy. Osobna część dotyczy przewidywania trajektorii.

Do wyboru sensorów potrzebny SPD; TFD nie zastępuje surowych obserwacji. Sprawdzić rzeczywisty dostęp do wybranego wydania i kod trackingu.

Źródła: [1](https://github.com/AIR-THU/DAIR-V2X-Seq).

### V2V4Real

Dwa współpracujące pojazdy; 20 tys. klatek LiDAR, 40 tys. obrazów RGB i ok. 240 tys. boxów 3D. Kod i opublikowane linki do wag.

Przy jednym potencjalnym współpracowniku wybór dotyczy głównie czy/kiedy zapytać. Potrzebne nowe percepcja i fuzja 3D; oficjalny pipeline używa CUDA/spconv.

Źródła: [1](https://arxiv.org/abs/2303.07601), [2](https://github.com/ucla-mobility/V2V4Real).

### TUMTraf-V2X

Realne auto i infrastruktura. Oficjalny benchmark podaje warianty vehicle, infrastructure i cooperative dla kamery, LiDAR i fuzji.

Migracja do detekcji 3D i zależności CoopDet3D. Wielu sensorów infrastruktury nie należy automatycznie liczyć jako wielu mobilnych agentów.

Źródła: [1](https://tum-traffic-dataset.github.io/tumtraf-v2x/).

### UrbanIng-V2X

34 sekwencje po około 20 s, 2 pojazdy i do 3 słupów infrastruktury w danej lokalizacji; RGB, thermal i LiDAR. Trzy skrzyżowania, kalibracje i timesync.

Thermal na infrastrukturze, RGB na pojazdach: modalność miesza się z pozycją źródła. Oficjalny pipeline 3D wymaga nowego środowiska. Nie zweryfikowano pobrania wag ani danych.

Źródła: [1](https://thi-ad.github.io/urbaning/), [2](https://github.com/thi-ad/UrbanIng-V2X).

### OPV2V

Syntetyczna współpraca V2V: ponad 70 scen, 11 464 klatki i ok. 233 tys. boxów pojazdów; istniejący pipeline OpenCOOD.

Dane symulowane i nowy pipeline detekcji 3D. Nie dowodzą działania na rzeczywistych sensorach ani realnego kosztu sieci.

Źródła: [1](https://arxiv.org/abs/2109.07644), [2](https://github.com/DerrickXuNu/OpenCOOD).

### V2XSet

Symulowana współpraca pojazdów i infrastruktury; repo V2X-ViT udostępnia konfigurację opóźnień i błędu lokalizacji oraz model referencyjny.

W CSV podano fork dwh68; właściwe repo autorów to DerrickXuNu/v2x-vit. Parametry komunikacji są symulowane, nie zmierzone.

Źródła: [1](https://github.com/DerrickXuNu/v2x-vit).

## Liczby z opublikowanych baseline’ów

Poniżej odejmujemy porównywalne wartości wewnątrz jednego benchmarku. Wartości mIoU i mAP należą do różnych zadań i nie służą do rankingu między datasetami. Warianty mogą mieć osobno trenowane sieci i różne koszty; przyrost nie jest zmierzoną korzyścią naszej polityki.

| Dataset | Metryka / wariant | Lokalny / RGB | Rozszerzony | Różnica, p.p. |
|---|---|---:|---:|---:|
| [TUMTraf-V2X](https://tum-traffic-dataset.github.io/tumtraf-v2x/) | 3D mAP, Average, LiDAR | 80.11 | 85.86 | +5.75 |
| [DeLiVER](https://github.com/InSAI-Lab/DELIVER) | mIoU, CMNeXt RGB → RGB-D-E-L | 57.20 | 66.30 | +9.10 |
| [DeLiVER](https://github.com/InSAI-Lab/DELIVER) | mIoU, CMNeXt RGB → RGB-E | 57.20 | 57.48 | +0.28 |
| [DeLiVER](https://github.com/InSAI-Lab/DELIVER) | mIoU, CMNeXt RGB → RGB-D | 57.20 | 63.58 | +6.38 |

W TUMTraf przytoczono oficjalną kolumnę Average dla vehicle-only LiDAR i cooperative LiDAR na tym samym teście. W DeLiVER wagi RGB-E dają tylko +0,28 p.p., podczas gdy RGB-D dają +6,38 p.p.; „więcej sensorów” samo w sobie nie gwarantuje większej użyteczności. W lokalnej dokumentacji PSTNet przytoczono opublikowane 67,66 → 68,37 mIoU, czyli +0,71 p.p. To nie jest wynik własnego pilota ani rozkład korzyści dla pojedynczych obrazów. [Lokalny status i zastrzeżenia](EXPERIMENTS.md).

## Ograniczenie dysku i wielkości pilota

Odczyt lokalny podczas przeglądu: C: około 3,4 GiB wolne, D: około 53,1 GiB wolne. To chwilowy stan. Rozmiary paczek wydawców są podane w GB; porównania z wolnym miejscem wykonano po przeliczeniu 1 GiB = 2³⁰ bajtów, 1 GB = 10⁹ bajtów.

SEW main: archiwum + rozpakowane pliki = 78 + 162 = 240 GB, około 223,5 GiB. SEW preview: 20 + 39 = 59 GB, około 54,9 GiB, czyli więcej niż obecnie wolne na D:. To dolna granica bez cache i predykcji. Nie uruchamiać standardowego pobierz-i-rozpakuj dla tych paczek przy obecnym miejscu. Pełny M2DGR (~1 TB) także odpada lokalnie. [Rozmiary SEW](https://github.com/SEW-Eurodrive-Open-Source/Multimodal_AMR_dataset), [M2DGR](https://github.com/SJTU-ViSYS/M2DGR).

Caltech RGB-T: pobranie 4,3 GB; rozmiar po rozpakowaniu jest jeszcze niezweryfikowany. DeLiVER: około 12,2 GB pobrania dla wydania front-view, również potrzebna rezerwa na rozpakowanie i wagi. UrbanIng pozwala pobrać jedną sekwencję; jej rozmiar trzeba odczytać przed pobraniem. Sam dostępny link nie potwierdza pełnego pobrania.

Przykładowy cache małych obrazów 640×360: RGB uint8 = 691 200 B, thermal uint8 = 230 400 B, razem 921 600 B/parę. Dla 10 000 par to 9,216 GB (8,58 GiB), bez masek, oryginałów i metadanych. Przy odpytywaniu thermal w 20% przypadków oszczędzamy 80% transferu thermal. Gdyby liczyć dostarczenie RGB i thermal razem, oszczędność wynosi tylko 20%: (4 − 3,2) / 4. W platformie RGB jest lokalne, więc główną metryką komunikacji pozostaje dodatkowy transfer peer observation.

Nie zapisywać pełnych logitów każdej sieci bez budżetu: jedna mapa 10 klas float32 przy 640×360 to 9 216 000 B, więc 10 000 map zajmuje 92,16 GB (85,83 GiB). Na pilota wystarczą predykcje, cechy polityki i statystyki błędu, o ile kontrakt fuzji nie wymaga pełnych wolumenów.

## Jak empirycznie ustalić, czy zbiór ma sens

1. Dla Caltech odczytać manifest małej paczki, potwierdzić wspólne RGB/T/maski, ignore index i płaszczyznę etykiet. Zacząć od kilkuset kompletnych par z różnych trajektorii i warunków. Dla UrbanIng najpierw jedna sekwencja do sprawdzenia loadera, timestampów, kalibracji, węzłów i wspólnego obszaru oceny. Jedna sekwencja nie wystarcza do wyniku naukowego.
2. Wybrać model lokalny i model fuzji z ustalonym kontraktem. Zweryfikować dostęp i zgodność wag przed większym pobieraniem. Jeżeli wag brak, oddzielnie oszacować koszt treningu. Oficjalne pipeline’y współpracy 3D korzystają z CUDA/spconv; nie potwierdzono ich działania w obecnym środowisku projektu.
3. Podzielić dane po trajektoriach/lokalizacjach na trening percepcji, trening polityki, walidację i nietknięty test. Pary RGB/T, widoki wszystkich agentów i sąsiednie klatki z jednej sceny muszą pozostać po tej samej stronie podziału. Dla UrbanIng kontrolować również skrzyżowania. Ukryte etykiety testowe MUSES/SEW oznaczają konieczność własnego podziału dostępnego treningu do lokalnego badania polityki.
4. Na zamrożonej percepcji zebrać offline wynik lokalny oraz wyniki po dołączeniu każdego dozwolonego źródła. Polityce online udostępniać wyłącznie lokalne cechy i jawne metadane, bez obrazów sąsiada, referencji i przyszłości. Koszt decyzji mierzyć oddzielnie od kosztu pozyskania.
5. Porównać stop, always, random, próg niepewności, wyuczoną politykę i diagnostyczny oracle przy tych samych budżetach, np. 10%, 25%, 50% i 100% zapytań. Raportować mIoU lub mAP, transfer bajtów, liczbę zapytań, zmierzony czas i jakość względem kosztu. Oracle jest górnym punktem odniesienia korzystającym z referencji, więc nie jest wdrażalną polityką.
6. Dla segmentacji ocenić globalne IoU z sumy macierzy pomyłek. Nie sumować przyrostów per-image mIoU jako globalnego mIoU. Do uczenia zysku można wybrać addytywny błąd pikselowy; końcową jakość policzyć osobno. Przy nieaddytywnym globalnym mIoU oracle budżetowy wymaga uwzględnienia wspólnej funkcji celu.
7. Utrzymać zbiór, jeżeli dodatkowe źródła dają użyteczne i zróżnicowane zyski, a selekcja poprawia krzywą jakość–koszt względem random/always. Decyzję oprzeć na powtórzeniach i przedziałach niepewności liczonych po sekwencjach, nie po silnie skorelowanych klatkach. Brak przewagi w jednym małym pilocie jest wynikiem nierozstrzygającym.

Dla UrbanIng osobno porównać współpracę LiDAR–LiDAR oraz dodawanie thermal z infrastruktury. Dzięki temu efekt nowej modalności nie będzie automatycznie utożsamiony z efektem nowego położenia źródła. Żaden z tych zbiorów sam nie zapewnia uczenia kolektywnego: poprawę z doświadczeń wielu agentów trzeba zdefiniować i zmierzyć w protokole.

## Składowe do ponownego przeliczenia

Tabela zachowuje kolejność pierwotnego CSV. Punktacje można zmienić w pliku review_inputs.json w lokalnym katalogu przeglądu i ponownie uruchomić build_review.mjs. Kod przeglądu nie modyfikuje modeli ani konfiguracji eksperymentów.

| Dataset | C | M | E | G | R | V | F | D |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Caltech Aerial RGB-Thermal | 0 | 2 | 5 | 4 | 3 | 5 | 3 | 5 |
| M2DGR | 0 | 5 | 1 | 5 | 3 | 5 | 1 | 3 |
| The Great Outdoors | 0 | 4 | 5 | 4 | 2 | 5 | 2 | 4 |
| SEW Multimodal AMR 2025 | 0 | 5 | 4 | 3 | 2 | 5 | 1 | 2 |
| CMHT Autonomous | 0 | 4 | 4 | 4 | 2 | 5 | 2 | 1 |
| MUSES | 0 | 4 | 5 | 3 | 4 | 5 | 2 | 1 |
| Seeing Through Fog | 0 | 5 | 4 | 4 | 3 | 5 | 2 | 1 |
| View of Delft | 0 | 3 | 4 | 4 | 4 | 5 | 2 | 1 |
| nuScenes | 0 | 3 | 4 | 5 | 5 | 5 | 1 | 1 |
| Oxford Radar RobotCar | 0 | 3 | 1 | 5 | 3 | 5 | 1 | 1 |
| Boreas | 0 | 3 | 4 | 5 | 4 | 5 | 1 | 1 |
| RADIATE | 0 | 3 | 4 | 4 | 3 | 5 | 2 | 1 |
| RaDelft | 0 | 3 | 2 | 4 | 3 | 5 | 1 | 1 |
| A2D2 | 0 | 2 | 5 | 3 | 4 | 5 | 2 | 1 |
| DeLiVER | 0 | 4 | 5 | 2 | 5 | 1 | 3 | 1 |
| FLIR ADAS | 0 | 2 | 4 | 2 | 3 | 5 | 3 | 1 |
| KAIST Multispectral Pedestrian | 0 | 2 | 4 | 2 | 4 | 5 | 3 | 1 |
| PST900 | 0 | 2 | 5 | 1 | 3 | 5 | 5 | 3 |
| DAIR-V2X | 3 | 2 | 4 | 3 | 4 | 5 | 2 | 1 |
| V2X-Seq | 3 | 2 | 4 | 5 | 3 | 5 | 1 | 1 |
| V2V4Real | 4 | 2 | 4 | 5 | 4 | 5 | 2 | 1 |
| TUMTraf-V2X | 3 | 2 | 4 | 4 | 4 | 5 | 1 | 1 |
| UrbanIng-V2X | 5 | 3 | 4 | 5 | 4 | 5 | 1 | 1 |
| OPV2V | 5 | 2 | 4 | 5 | 5 | 1 | 2 | 1 |
| V2XSet | 5 | 2 | 4 | 5 | 4 | 1 | 2 | 1 |

## Pochodzenie i zakres

Wejście: niezmieniony CSV z Pobranych, doktorat_multimodal_dataset_landscape_links(Datasets).csv. SHA256: 9e6dc9397e57659158a6b10df9faa2a5fb1c6247644e2338c97597383ec48d4e. Kontekst platformy: [README](../README.md), [dane](DATA.md), [eksperymenty](EXPERIMENTS.md), [zasoby](RESOURCES.md) i wcześniejszy czat „Plan platformy symulacyjnej”. Każdy wiersz ma odnośnik do źródła autorów lub publikacji. W części przypadków pierwotny link prowadził do forka lub niedziałającej strony; użyto repozytorium autorów albo publikacji.

Dostępność stron nie jest testem dostępności pełnych danych lub checkpointów. Nie mierzono liczby kompletnych próbek nowych zbiorów, ich rzeczywistych rozmiarów po rozpakowaniu poza deklaracjami SEW ani czasu treningu. Nie wykonano pomiaru GPU, energii lub przepustowości sieci. Wartości te pozostają do sprawdzenia podczas pilota.
