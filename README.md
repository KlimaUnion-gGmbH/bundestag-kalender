# Bundestag-Kalender

Kalenderabos (iCal) mit der Tagesordnung des Plenums des Deutschen Bundestages und den Terminen des Ausschusses für Wirtschaft und Energie.

Betrieben von der **KlimaUnion gGmbH**, Berlin ([klimaunion.org](https://klimaunion.org)). Das Angebot stellt öffentliche Parlamentsdaten des Bundestages für die energie- und klimapolitische Informationsarbeit bereit. Es enthält keine eigenen Bewertungen, nur Termine, Zuordnungen und Links auf amtliche Dokumente. Inoffiziell, ohne Gewähr.

Startseite mit Abo-Links: <https://klimaunion-ggmbh.github.io/bundestag-kalender/>

## Feeds

| Datei | Inhalt |
|---|---|
| `bundestag.ics` | alle Tagesordnungspunkte des Plenums und die Sitzungswochen |
| `bundestag-wirtschaft-energie.ics` | Plenarpunkte, bei denen der Ausschuss für Wirtschaft und Energie federführend ist oder die Beschlussempfehlung vorlegt |
| `bundestag-wirtschaft-energie-ausschuss.ics` | Sitzungen und öffentliche Anhörungen dieses Ausschusses |
| `bundestag-wirtschaft-energie-komplett.ics` | alle drei zusammen |
| `bundestag-umwelt-klima.ics` | Plenarpunkte, bei denen der Ausschuss für Umwelt, Klimaschutz, Naturschutz und nukleare Sicherheit federführend ist oder die Beschlussempfehlung vorlegt |

Die Termine enthalten Ort, Status, Links auf Drucksachen, Plenarprotokolle, Tagesordnungen, Sachverständigenlisten und Stellungnahmen. Dieselben PDFs hängen zusätzlich als Anhangs-Link am Termin (je nach Kalenderprogramm sichtbar). Die Dateien selbst werden nicht kopiert.

## Datenquellen

- Tagesordnung des Plenums und Textarchiv: [bundestag.de](https://www.bundestag.de)
- Sitzungswochen: offizielle Kalenderdateien auf bundestag.de
- Ausschusssitzungen und Anhörungen: Ausschussseiten auf bundestag.de
- Überweisungen an Ausschüsse, Plenarprotokolle: [DIP, Dokumentations- und Informationssystem des Bundestages](https://dip.bundestag.de)

## Ausschuss-Zuordnung

Quellen in absteigender Verlässlichkeit:

1. Tagesordnung: Beschlussempfehlung und Bericht eines Ausschusses. Amtlich.
2. DIP: Überweisungen je Drucksache, federführend und mitberatend. Amtlich.
3. Tagesordnung: Überweisungsvorschlag. Nur ein Vorschlag.
4. Textarchiv-Artikel: Hinweis auf die vorgesehene Federführung. Nur ein Vorschlag.

Der Bundestag beschließt die Überweisung erst in der ersten Beratung. Termine, die nur auf einem Vorschlag beruhen, tragen "(Ausschuss-Vorschlag)" im Titel. Nach der Überweisung ersetzt DIP den Vorschlag.

## Grenzen

- Endzeiten der Plenarpunkte und nicht öffentlicher Ausschusssitzungen sind geschätzt. Der Bundestag veröffentlicht nur Startzeiten.
- Namentliche Abstimmungen sind in den Quelldaten nicht markiert.
- Die Inhalte einzelner Ausschuss-Tagesordnungen stehen nur im verlinkten PDF.
- Die genutzten Schnittstellen von bundestag.de sind nicht offiziell dokumentiert und können sich ändern.
- Abonnierte Kalender werden von vielen Programmen nur alle paar Stunden aktualisiert.

## Technik

Ein Python-Skript (nur Standardbibliothek) erzeugt die Feeds. GitHub Actions führt es Mittwoch bis Freitag etwa alle 15 Minuten, sonst stündlich, aus und veröffentlicht das Ergebnis über GitHub Pages.

- `2026-10-12_bundestag_kalender.py`: Skript
- `.github/workflows/`: Zeitplan und Veröffentlichung
- `docs/`: erzeugte Feeds und Startseite
- `cache/`: Zwischenspeicher, damit abgeschlossene Abfragen nicht wiederholt werden

Die Ausschuss-Zuordnung nutzt die DIP-API des Bundestages. Der öffentliche Schlüssel des Bundestages ist im Skript hinterlegt und gilt bis Ende Mai 2027. Ein eigener Schlüssel kann als Repository-Secret `DIP_API_KEY` eingetragen werden.
