# Framework selektywnego pozyskiwania informacji — user stories i MVP

Data: 2026-10-14  
Status: brief do implementacji w Codexie, wersja 1.0  
Technologia pierwszej wersji: Python

## 1. Cel i sposób pracy

Budujemy framework badawczy, w którym heterogeniczni agenci decydują, czy warto pozyskać dodatkową informację, od kogo lub z jakiego źródła, uwzględniając niepewność, oczekiwaną korzyść i koszt. Agenci mogą współdzielić bieżącą wiedzę oraz uczyć się na doświadczeniach innych agentów.

Pierwsze zastosowanie może dotyczyć RGB i termowizji, ale rdzeń ma obsługiwać także sygnały czasowe, wyniki pomiarów i dane tabelaryczne. Domena medyczna jest przykładem przyszłego zastosowania, a nie wymaganiem wdrożenia klinicznego. Agent nie jest synonimem drona, urządzenia ani pojedynczego sensora.

Ten plik jest samodzielnym briefem. Wcześniejszy obszerny dokument architektury pozostaje materiałem pomocniczym; ten brief określa zakres obecnego MVP. Pracujemy poprzez małe, uruchamialne przyrosty. Nie implementuj od razu całej architektury opisywanej we wcześniejszych materiałach.

**Instrukcja startowa dla Codexa:** sprawdź istniejące repozytorium i jego instrukcje, dopasuj nazwy do zastanego kodu i wykonaj etap 1 opisany poniżej. Kolejne etapy są uporządkowanym backlogiem. Jeśli użytkownik wskaże inny zakres, kieruj się jego zadaniem. Nie usuwaj wcześniejszych eksperymentów ani nie zastępuj ich nowym szkieletem bez potrzeby.

## 2. Co chcemy badać

Interesuje nas wybór dodatkowej informacji zależny od aktualnej wiedzy odbiorcy, dostępnych modalności, kontekstu i kosztu. Szczególnie ważne jest pytanie, czy doświadczenia jednych agentów pomagają innym lepiej przewidywać przydatność kolejnych obserwacji.

Kierunek wkładu badawczego: uczenie użyteczności informacji z doświadczeń heterogenicznych agentów, z uwzględnieniem tego, komu i w jakich warunkach informacja pomaga. Jest to hipoteza badawcza do weryfikacji, a nie deklaracja potwierdzonego novum. Sam ogólny framework lub dodanie uczenia federacyjnego nie jest dowodem nowości.

Framework ma umożliwić porównanie:

- decyzji bez dodatkowego pozyskiwania, prostych polityk bazowych i polityki przewidującej korzyść;
- scentralizowanego i zdecentralizowanego podejmowania decyzji;
- uczenia lokalnego i uczenia ze wspólnych doświadczeń;
- jakości wyników przy porównywalnych budżetach i dostępnej informacji.

## 3. Uzgodnione zasady

| Obszar | Decyzja |
| --- | --- |
| Implementacja | Python; kompozycja prostych komponentów, bez Rust na starcie. |
| Domena | Rdzeń niezależny od dronów, obrazów i geometrii. |
| Agent i źródło | Agent podejmuje decyzje i ma stan. Źródło dostarcza obserwacje. Jeden agent może mieć wiele źródeł i modalności. |
| Informacja | Agent widzi tylko własne udostępnione dane oraz rzeczywiście otrzymane wiadomości. |
| Koszt | Osobno estymata przed działaniem i koszt rozliczony po działaniu. |
| Użyteczność | Osobno przewidywana korzyść i zmierzony efekt; niepewność nie jest tym samym co poprawność. |
| Kolektywność | Współpraca jest konfigurowalna, a współdzielone uczenie jest częścią zakresu MVP. |
| Wykonanie | Na początku jeden proces i deterministyczna kolejność zdarzeń; decentralizacja jest logiczna, bez wymagania osobnych serwerów. |

### Trzy niezależne decyzje projektowe

| Mechanizm | Pytanie | Przykładowe warianty |
| --- | --- | --- |
| Koordynacja decyzji | Kto wybiera działanie? | Centralny koordynator albo lokalni agenci. |
| Wymiana bieżącej wiedzy | Co, komu i kiedy przekazujemy? | Raporty do centrum, wiadomości między agentami, brak wymiany. |
| Wspólne uczenie | Jak doświadczenie jednego agenta poprawia modele innych? | Uczenie lokalne, wspólny zbiór doświadczeń, później federacja lub peer-to-peer. |

Te mechanizmy konfigurujemy oddzielnie i walidujemy ich zgodność. Dopuszczalny jest agent decydujący lokalnie z modelem uczonym okresowo przez centralnego agregatora. Dopuszczalne są też grupy z własnymi koordynatorami, ale hierarchia nie jest obowiązkowa w MVP.

Wspólny bufor przechowuje informacje. Decyzje podejmuje koordynator za pomocą polityki. Bufor bieżącej wiedzy i zbiór doświadczeń do uczenia mają różne role i nie dają automatycznie tego samego dostępu do danych.

## 4. User stories

### US-01 — Definiuję agenta

**Jako badacz chcę zdefiniować agenta z modalnościami, źródłami obserwacji, lokalnym cache, modelem percepcyjnym i opcjonalnymi metadanymi.**

Kryteria akceptacji:

- Agent ma identyfikator, dostępne modalności i źródła oraz konfigurowalny model lub pipeline percepcji.
- Modalności mają znaczące nazwy i opis; nie ograniczamy konfiguracji do RGB i thermal.
- Metadane, np. położenie, rola lub parametry urządzenia, są opcjonalne. Rdzeń nie wymaga współrzędnych.
- Cache zawiera obserwacje już dostarczone. Powtórne użycie danych z cache nie oznacza nowego pozyskania; koszt ponownego przetwarzania można zdefiniować osobno.
- Wynik percepcji można powiązać z wejściowymi obserwacjami i wersją modelu.

### US-02 — Definiuję zadanie i przedmiot decyzji

**Jako badacz chcę określić, co system ma ustalić, czego dotyczy decyzja i kiedy zadanie się kończy.**

Kryteria akceptacji:

- Zadanie określa rodzaj wyniku, metrykę jakości, warunek zakończenia i ewentualny budżet.
- Każda obserwacja i decyzja odnosi się do `TargetRef`. Na start wystarczą `kind="sample"` oraz `id`.
- Ten sam identyfikator próbki może łączyć modalności tylko na podstawie jawnego mapowania dostarczonego przez adapter danych.
- Geometria i układ współrzędnych są opcjonalnymi rozszerzeniami. Wspólna próbka nie oznacza automatycznie zgodności pikseli, widoków ani czasu pomiaru.
- Jeśli konkretna metoda wymaga wyrównania danych, adapter musi je zapewnić, a walidacja odrzuca brak wymaganej zgodności.
- Polityka może zakończyć pozyskiwanie i zwrócić aktualny wynik; jeśli zadanie dopuszcza brak rozstrzygnięcia, wynik może to jawnie wskazywać.

### US-03 — Wybieram sposób podejmowania decyzji

**Jako badacz chcę przełączać koordynację scentralizowaną i zdecentralizowaną oraz niezależnie wybierać algorytm selekcji informacji.**

Kryteria akceptacji:

- W wariancie centralnym agenci przekazują jawne raporty do wspólnego bufora, a koordynator wybiera działania dla agentów.
- W wariancie zdecentralizowanym każdy agent decyduje na podstawie swojego stanu i otrzymanych wiadomości.
- Algorytm wyboru, np. próg niepewności lub przewidywana korzyść względem kosztu, jest wymienny bez przebudowy źródeł i modeli percepcji.
- Polityka dostaje ograniczony widok stanu, dostępne akcje i dozwolone estymaty. Nie dostaje pełnego datasetu ani etykiet testowych.
- Każda decyzja wskazuje odbiorcę informacji, cel i wybraną akcję albo zakończenie. Centralny widok nie oznacza automatycznego dostępu do wszystkich cache.

### US-04 — Pozyskuję obserwację

**Jako badacz chcę, aby wybrana akcja pobrała obserwację z właściwego źródła i dostarczyła ją wskazanemu odbiorcy.**

Kryteria akceptacji:

- Żądanie wskazuje źródło, cel, odbiorcę i potrzebne parametry.
- Źródłem może być dataset, urządzenie lub generator; w MVP używamy źródła lokalnego.
- Dostępne akcje wynikają z jawnych możliwości źródła. Lista możliwości nie ujawnia ukrytych wartości obserwacji.
- Wynik opisuje sukces, błąd albo przerwanie. Cache aktualizuje się po dostarczeniu danych, nie po samym wyborze akcji.
- Próby nieudane także trafiają do dziennika i mogą ponosić koszt.
- Pierwsza wersja może wykonywać żądania sekwencyjnie. Ograniczenia współdzielonego źródła są respektowane; nie obiecujemy równoległego wykonania bez modelu dostępności.

### US-05 — Definiuję i rozliczam koszt

**Jako badacz chcę przewidywać koszt przed pozyskaniem i oceniać go po wykonaniu.**

Kryteria akceptacji:

- Estymata powstaje z akcji i wiedzy dostępnej przed jej wykonaniem. Nie może zależeć od jeszcze niepozyskanej obserwacji.
- Koszt po wykonaniu wynika z raportu wykonania. Obie wartości są zapisywane osobno; nie nadpisujemy przewidywania wynikiem.
- Model kosztu może być stałą, funkcją, tabelą lub później modelem uczonym. W MVP wystarczy stała lub funkcja.
- Koszt może mieć kilka jawnych składowych z jednostkami, np. czas, bajty, energię lub liczbę zapytań. Nie sumujemy różnych jednostek bez zdefiniowanego przeliczenia.
- Scenariusz wybiera składowe, budżety i ewentualną funkcję sprowadzającą je do jednej wartości. Brak pomiaru jest oznaczony jako brak, a nie jako zero.
- Koszt komunikacji lub przetwarzania można włączyć osobno. Nie narzucamy sztucznego modelu lotu, energii ani ruchu wszystkim eksperymentom.
- W symulacji rozliczony koszt oznacza wynik zadeklarowanego modelu scenariusza. Nie opisujemy go jako pomiaru fizycznego urządzenia.
- Sposób obsługi przekroczenia budżetu jest jawny. Estymata nie gwarantuje, że rzeczywisty koszt nie przekroczy limitu; zapisujemy takie zdarzenie i stosujemy regułę scenariusza.

### US-06 — Aktualizuję wiedzę i wynik

**Jako badacz chcę określić, jak nowa obserwacja zmienia wiedzę agenta i jego wynik zadania.**

Kryteria akceptacji:

- Po dostarczeniu informacji uruchamiamy właściwe przetwarzanie i aktualizujemy wynik.
- Reguła łączenia informacji jest wymienna: może używać ostatniego pomiaru, łączyć predykcje albo korzystać z dedykowanego modelu.
- Przechowywanie w cache i fuzja wyników są rozdzielone.
- Metoda deklaruje obsługiwane wejścia. Inne modalności, niezgodne cele lub brak wymaganego mapowania nie są automatycznie traktowane jako zgodne.
- Prosta fuzja w przykładzie wystarcza; nie implementujemy od razu biblioteki wszystkich rodzajów fuzji.

### US-07 — Przewiduję i mierzę korzyść

**Jako badacz chcę ocenić, czy dodatkowa informacja była warta pozyskania, oraz uczyć się przewidywać jej przydatność.**

Kryteria akceptacji:

- Przewidywana korzyść zależy od aktualnego stanu odbiorcy, celu i kandydującej akcji. Ta sama informacja może mieć różną wartość dla różnych agentów.
- Po pozyskaniu porównujemy wynik przed i po przy użyciu metryki zadania. Definicja korzyści i jej kierunek są jawne; pogorszenie pozostaje wartością ujemną.
- Spadek niepewności można zapisać jako osobny wskaźnik. Nie uznajemy go automatycznie za poprawę poprawności.
- Etykiety referencyjne i korzyść znana dopiero po wykonaniu nie są dostępne polityce przed decyzją.
- Jeśli nie można ocenić rzeczywistej korzyści, zapisujemy brak wartości. Etykiety z testu mogą służyć ewaluatorowi, ale nie aktualizacjom modelu używanego w tym teście.
- Na początku wystarcza heurystyka selekcji; uczony predyktor użyteczności wprowadzamy w etapie 3.

### US-08 — Definiuję współpracę i wspólne uczenie

**Jako badacz chcę określić, czym, z kim i kiedy agenci się dzielą oraz jak doświadczenia jednych poprawiają decyzje innych.**

Kryteria akceptacji:

- Osobno konfigurujemy wymianę wiedzy w trakcie zadania oraz współdzielenie doświadczeń lub aktualizacji modeli do uczenia.
- Strategia określa zawartość wiadomości, odbiorców, moment wysłania i sposób wykorzystania. Samo istnienie wspólnego magazynu nie udostępnia jego zawartości każdemu agentowi.
- W MVP obsługujemy brak wymiany, raporty do koordynatora oraz prostą wymianę raportów między agentami. Wystarcza transport w pamięci procesu z jawnym dostarczeniem wiadomości.
- W MVP porównujemy model użyteczności uczony lokalnie z modelem uczonym centralnie na wspólnych doświadczeniach treningowych. Następnie agenci mogą korzystać z wytrenowanych modeli przy lokalnych decyzjach.
- Doświadczenie zachowuje kontekst sprzed działania, identyfikator odbiorcy i jego możliwości, akcję, status wykonania, koszt oraz zaobserwowaną korzyść. Zapisujemy też pochodzenie i wersje modeli.
- Wspólny model wymaga zgodnego opisu wejść i znaczenia celu uczenia. Nie uśredniamy automatycznie wag różnych modeli percepcyjnych ani korzyści z różnych zadań i metryk.
- Koszty wiadomości podczas zadania oraz transferów i treningu między epizodami raportujemy oddzielnie. Koszt wyłączony z eksperymentu jest jawnie wyłączony, a nie przedstawiony jako zmierzone zero.

Uczenie federacyjne, peer-to-peer, personalizacja i koordynatorzy grupowi są późniejszymi strategiami współpracy. Federacja oznacza tu uczenie lokalne i uzgodnione łączenie aktualizacji kompatybilnych modeli, a nie samą obecność centralnego bufora.

### US-09 — Uruchamiam porównywalny eksperyment

**Jako badacz chcę skonfigurować scenariusz, uruchomić różne strategie i porównać jakość, koszty oraz wykorzystanie informacji.**

Kryteria akceptacji:

- Scenariusz określa dane, agentów, wiedzę początkową, dostępność źródeł, zadanie, strategie, koszty, ograniczenia i ziarno losowości.
- Porównania używają tych samych podziałów danych, warunków początkowych i zasad budżetu. Różnice wynikające ze strategii są widoczne w logach.
- Zapisujemy decyzje, identyfikatory obserwacji i wiadomości, estymaty i wyniki kosztów/korzyści, jakość oraz przyczynę zakończenia.
- Raport uwzględnia wyniki agentów i jawną metrykę zespołu, np. średnią jakość oraz sumę kosztów. Nie zakładamy, że suma lokalnych korzyści zawsze jest korzyścią zespołu.
- Dane treningowe, walidacyjne i testowe są rozdzielone zgodnie z jednostką niezależności scenariusza, np. osobą lub sekwencją. Model współdzielony nie trenuje na doświadczeniach testowych.
- Konfiguracja, wersje modeli, podział danych i seed pozwalają odtworzyć przykład.

## 5. Minimalny przepływ wykonania

1. Scenariusz dostarcza jawnie określoną wiedzę początkową.
2. Agent lub koordynator tworzy widok wiedzy dostępnej w tej chwili.
3. Wyznaczamy wykonalne akcje i przewidujemy ich koszt oraz, jeśli dostępna, korzyść.
4. Polityka wybiera pozyskanie albo zakończenie.
5. Wykonujemy akcję, rozliczamy jej koszt i dostarczamy wynik odpowiedniemu odbiorcy.
6. Aktualizujemy cache, percepcję i wynik zadania; realizujemy jawnie skonfigurowaną wymianę raportów.
7. Ewaluator zapisuje efekt i doświadczenie. Wracamy do wyboru albo kończymy epizod.
8. W zadeklarowanym momencie uczymy lokalnie lub ze wspólnych doświadczeń treningowych i udostępniamy nową wersję modelu.

Na początku uczenie odbywa się między epizodami treningowymi lub offline, a modele są zamrożone podczas ewaluacji testowej. Nie wymagamy uczenia online w pierwszym MVP.

Minimalny zapis doświadczenia powinien pozwalać odtworzyć relację:

`stan odbiorcy przed akcją → wybrana akcja → wynik wykonania → korzyść i koszt`

Kontekst do przewidywania zachowujemy w wersji sprzed akcji. Pełne dane nie muszą być kopiowane do każdego wpisu; można używać identyfikatorów i kontrolowanych odwołań. Obserwacje i doświadczenia potrzebują stabilnych identyfikatorów, aby ponowne przesłanie tego samego zdarzenia nie podwajało informacji ani naliczonego kosztu.

## 6. Wskazówki implementacyjne

- Dopasuj układ do istniejącego repozytorium. Preferuj małe moduły, typy danych i składane funkcje/obiekty. `dataclass` i `Protocol` są opcjami, nie obowiązkiem dla każdego pojęcia.
- Rozdziel odpowiedzialności: źródła danych, stan agenta, zadanie/fuzja, wybór akcji, koordynacja, wymiana informacji, koszt, uczenie i wykonanie eksperymentu.
- Nie muszą to być osobne klasy ani pakiety. Interfejs wydzielaj tam, gdzie faktycznie wymieniamy zachowanie.
- Rdzeń nie importuje bibliotek właściwych tylko dla dronów lub konkretnych sensorów. Adaptery mają dostarczać znaczenie danych i wymagane mapowania.
- Symulator może posiadać ukryte obserwacje i etykiety; interfejs polityki nie może ich ujawniać. Testuje się granice przekazywanych danych, a nie bezpieczeństwo wobec złośliwego kodu Pythona.
- Wspólne zasoby obsługuj przez jawne reguły dostępności. Globalna kolejka wykonania nie może ujawniać agentom cudzych informacji.
- Rozliczaj każdą składową kosztu raz: np. koszt pozyskania i koszt przekazania mogą być odrębne, ale ten sam transfer nie może zostać policzony ponownie przez dwa komponenty.
- Zacznij od zwykłej konfiguracji Pythona i prostego eksportu wyników, np. JSONL. Nie wprowadzaj rozbudowanego DSL, brokera, bazy danych ani platformy rozproszonej bez konkretnej potrzeby.

## 7. Kolejność implementacji

### Etap 1 — Pełna pętla dla jednego agenta

Domyślny zakres pierwszego zadania dla Codexa.

- Jeden agent, dwie nazwane modalności i lokalne źródło danych.
- `TargetRef` na poziomie próbki, cache, prosta percepcja i aktualizacja wyniku.
- Akcje pozyskania i zakończenia, reguła selekcji oraz warunek końca.
- Osobne przewidywanie i rozliczanie kosztu, w tym kontrolowany przypadek błędu pozyskania.
- Log decyzji i ewaluacja jakości przed/po.
- Baseline bez dodatkowych obserwacji i prosta selektywna polityka.

**Gotowe, gdy:** pojedyncza komenda uruchamia powtarzalny przykład od konfiguracji po raport, a log pokazuje, jakie dodatkowe dane były rzeczywiście dostępne agentowi i ile kosztowały. Przykład może używać małych syntetycznych danych liczbowych z komplementarnymi źródłami informacji; nie wymaga GPU, drona ani zewnętrznego datasetu.

### Etap 2 — Wielu agentów i wymienna koordynacja

- Kilku agentów z różnymi źródłami, modalnościami lub informacją początkową.
- Wariant centralny ze wspólnym buforem jawnych raportów.
- Wariant zdecentralizowany z lokalnymi widokami i jawną wymianą wiadomości.
- Rejestr dostarczenia wiadomości, konfigurowalne koszty wymiany i metryki zespołu.
- Ten sam scenariusz uruchamiany z obiema strategiami koordynacji.

**Gotowe, gdy:** można wykazać z logów, dlaczego dany agent lub koordynator znał informację w chwili decyzji. Zmiana koordynacji nie wymaga zmiany źródeł, modeli percepcji ani definicji zadania.

### Etap 3 — Kolektywne uczenie użyteczności

- Zbieranie doświadczeń na oddzielnym zbiorze treningowym według jawnej polityki zbierania danych, obejmującej różne dostępne akcje.
- Prosty predyktor korzyści, np. mały model regresyjny, oparty na kontekście dostępnym przed akcją.
- Wariant lokalny: każdy agent uczy się na własnych doświadczeniach.
- Wariant wspólny: model uczy się na zgodnie opisanych doświadczeniach grupy i jest udostępniany lokalnym agentom.
- Ewaluacja na odłożonych danych, z zamrożonymi modelami i porównywalnymi budżetami.

**Gotowe, gdy:** eksperyment porównuje heurystykę, lokalne uczenie i wspólne uczenie oraz pokazuje jakość, liczbę pozyskań, koszt i błędy przewidywania korzyści. Raport opisuje liczebność i pochodzenie danych treningowych oraz koszt współpracy. Nie wymaga się, by wspólne uczenie zawsze wygrywało; negatywny wynik także jest poprawnym wynikiem eksperymentu.

**Pełne MVP obejmuje etapy 1–3.** Zakończenie etapu 1 jest pierwszym przyrostem, a nie zakończeniem całego frameworka. Etap 3 jest obowiązkowy dla deklaracji, że MVP obejmuje uczenie kolektywne.

## 8. Najważniejsze sprawdzenia poprawności

Dobierz małe testy do ryzyk faktycznie wprowadzanego etapu. Nie buduj od razu ogromnej macierzy testów.

1. Polityka nie otrzymuje niepozyskanych danych, etykiet testowych ani informacji z cudzych cache bez dostarczenia wiadomości.
2. Estymata kosztu jest zachowana, nawet gdy koszt po wykonaniu jest inny; nieudana próba jest rozliczana i nie tworzy udanej obserwacji.
3. Nie mieszamy informacji o różnych celach i nie pomijamy wymaganego mapowania modalności.
4. Brak dostępnej akcji, zakończenie lub reguła budżetu kończy epizod bez nieskończonej pętli; ponowne użycie cache nie nalicza nowego pozyskania.
5. Ujemna korzyść pozostaje ujemna, a brak etykiety nie jest traktowany jak zerowa korzyść.
6. Dostarczenie wiadomości zmienia wiedzę tylko określonych odbiorców; ponowne dostarczenie tego samego identyfikatora nie podwaja efektu.
7. Wspólne uczenie używa wyłącznie dozwolonych doświadczeń treningowych, a decyzje testowe korzystają z zamrożonych modeli.
8. Przykład daje odtwarzalne wyniki dla tej samej konfiguracji i ziarna losowości.

## 9. Poza zakresem pierwszego MVP

- Rust, mikroserwisy, rzeczywisty transport sieciowy i wdrożenia urządzeń.
- Symulacja lotu, planowanie trajektorii, rejestracja obrazów i cyfrowe modele aparatury w rdzeniu.
- Pełna federacja, dowolne topologie hierarchiczne, zaawansowana personalizacja i transfer między dziedzinami.
- Automatyczne łączenie wag niezgodnych modeli albo gwarancja poprawy dzięki kolektywności.
- Obsługa wszystkich datasetów i typów zadań naraz; jeden mały działający scenariusz wystarcza do pierwszego przyrostu.

Interfejsy mają umożliwiać późniejsze rozszerzenia. Nie tworzymy pustych implementacji każdej przyszłej strategii tylko po to, żeby zapełnić architekturę.

## 10. Oczekiwany raport Codexa po etapie

Po wykonaniu wskazanego etapu podaj:

- co działa i które user stories pokrywa;
- komendę uruchamiającą przykład oraz lokalizację wyników;
- jakie sprawdzenia wykonano i jaki był wynik;
- przyjęte uproszczenia i najbliższy kolejny etap.

README i przykład mają być zgodne z działającym kodem. Nie deklaruj zakończenia pozostałych etapów na podstawie samych interfejsów, atrap lub listy planowanych klas.
