# LIVE tracking, strefy i konfiguracja urządzenia

Status: implemented for release `v0.8.0`.

## Podsumowanie

- Dodać ręczny switch LIVE dla każdego urządzenia GPS z IMEI, ignorując
  `allowLiveMode`.
- Podczas LIVE zatrzymać polling `devicelist`; po zakończeniu wykonać
  natychmiastowy refresh REST.
- Usunąć użycie `devicesamples` i sensor historii.
- Dodać edycję interwałów oraz alarmów prędkości i baterii.
- Dodać osobny wybór encji `zone.*` dla każdego urządzenia.
- Dodać opcjonalny wybór encji `binary_sensor.*` oznaczającej połączenie
  urządzenia z garażem.

## Automatyzacja strefy

- LIVE uruchamia się po wejściu urządzenia do standardowego promienia wybranej
  strefy HA. Aby uzyskać próg 500 m, strefa powinna mieć promień `500 m`.
- Odległość obliczać ze współrzędnych `lastPosition` i atrybutów `latitude`,
  `longitude`, `radius` encji strefy.
- Pozycja REST wykrywa pierwsze wejście, a próbki WS kontrolują dalszą obecność
  w strefie.
- Automatycznie uruchomiony LIVE zatrzymać po opuszczeniu strefy.
- Strefa nie zatrzymuje sesji uruchomionej ręcznie.
- Po błędzie, limicie lub ręcznym wyłączeniu ponowny automatyczny start wymaga
  opuszczenia strefy i ponownego wejścia.
- Po restarcie HA urządzenie znajdujące się już w strefie może rozpocząć jedną
  automatyczną sesję.
- Zmiany położenia lub promienia encji strefy mają natychmiast przeliczać stan.
- Niedostępna strefa albo brak współrzędnych wyłącza automatykę bez
  zatrzymywania ręcznej sesji.

## Automatyczne zatrzymanie LIVE

- Zatrzymać każdą sesję LIVE, ręczną i uruchomioną przez strefę, gdy notiOne
  zgłosi dla urządzenia stan `OFFLINE`.
- Zatrzymać każdą sesję LIVE, gdy przypisana do urządzenia encja garażu
  `binary_sensor.*` przejdzie do stanu `on`.
- Encję garażu wybierać osobno dla każdego urządzenia; brak wyboru wyłącza ten
  warunek automatyzacji.
- Stan `off`, `unknown` lub `unavailable` encji garażu nie uruchamia ani nie
  zatrzymuje LIVE.
- Po automatycznym zatrzymaniu z powodu `OFFLINE` lub połączenia z garażem nie
  uruchamiać ponownie LIVE, dopóki urządzenie nie opuści strefy i nie wejdzie do
  niej ponownie albo użytkownik nie włączy trybu ręcznie.
- Po zatrzymaniu zamknąć WebSocket kodem klienta `3000`, przywrócić polling
  `devicelist` i zapisać przyczynę zakończenia w atrybutach switcha LIVE.

## LIVE WebSocket

- Użyć `aiohttp` WebSocket i binarnego protokołu protobuf:
  - wysłanie IMEI,
  - odbiór limitu sesji i próbek GPS,
  - mapowanie próbek na `lastPosition`,
  - obsługa kodów `4000-4005`,
  - ręczne zamknięcie kodem `3000`.
- Switch pokazuje stan łączenia i aktywnej sesji oraz automatycznie wraca do
  `OFF` po zamknięciu.
- Atrybuty zawierają źródło uruchomienia (`manual` lub `zone`), limit sesji,
  kod zamknięcia i powód.
- Nie odnawiać automatycznie sesji po limicie serwera.
- Przy wyładowaniu integracji zamknąć sockety i zadania.

## Ustawienia urządzenia

- `select`: interwał ruchu z `allowedMoveIntervals`.
- `select`: interwał postoju `1 h`, `6 h`, `24 h`.
- `switch` i `number`: alarm prędkości oraz próg.
- `switch`, `number` i `select`: alarm baterii, próg i interwał.
- `button`: ręczne odświeżenie `deviceconfig`.
- Konfigurację pobierać przy starcie, po zapisie i po ręcznym odświeżeniu.
- Zapisywać jako `GET -> zmiana pola -> POST pełnego modelu -> GET`, z blokadą
  równoległych operacji.
- Alarm kradzieży, eTOLL, Strava i wyłączanie urządzenia pozostają poza
  zakresem.

## Testy

- Przetestować protobuf, aktualizację pozycji, pauzowanie REST i kody zamknięcia
  WS.
- Przetestować ręczne oraz strefowe uruchamianie, opuszczenie strefy, ponowne
  uzbrojenie i restart HA.
- Przetestować zatrzymanie sesji ręcznej i strefowej po stanie `OFFLINE` oraz po
  aktywacji przypisanej encji garażu.
- Przetestować stany `off`, `unknown` i `unavailable` encji garażu oraz brak jej
  konfiguracji.
- Przetestować wiele urządzeń z różnymi strefami oraz zmianę promienia strefy.
- Przetestować bezpieczny zapis konfiguracji i odświeżenie ręczne.
- Usunąć `DEVICESAMPLES_URL`, metodę historii, `_history_gpstime` oraz
  `last_seen_history`.
