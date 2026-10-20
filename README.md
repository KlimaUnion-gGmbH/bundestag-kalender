# Bundestag-Kalender

Erzeugt Kalenderdateien (iCal) mit der Tagesordnung des Plenums des Deutschen Bundestages und den Terminen ausgewählter Ausschüsse (Wirtschaft und Energie, Umwelt, Verkehr, Wohnen). Grundlage sind öffentliche Parlamentsdaten. Inoffiziell, ohne Gewähr.

## Kalender

| Kalender | Inhalt |
|---|---|
| Plenum komplett | alle Tagesordnungspunkte des Plenums und die Sitzungswochen |
| Ausschuss komplett (je Ausschuss) | Plenarpunkte, bei denen der Ausschuss federführend ist oder die Beschlussempfehlung vorlegt, dazu die Sitzungen des Ausschusses mit Sitzungsnummer und seine öffentlichen Anhörungen |
| Teile eines Ausschuss-Kalenders | nur die Plenarpunkte oder nur die Sitzungen und Anhörungen, jeweils als Teil des "komplett"-Kalenders gekennzeichnet |

Anhörungen zählen als zusätzliche Sitzungen neben der regulären Sitzung in der Sitzungswoche. Die Termine enthalten Ort, Status und Links auf amtliche Dokumente. Die Dateien selbst werden nicht kopiert.

## Datenquellen

- Tagesordnung des Plenums und Textarchiv: bundestag.de
- Sitzungswochen: offizielle Kalenderdateien auf bundestag.de
- Ausschusssitzungen und Anhörungen: Ausschussseiten auf bundestag.de
- Überweisungen an Ausschüsse, Plenarprotokolle: DIP, Dokumentations- und Informationssystem des Bundestages

## Ausschuss-Zuordnung

Quellen in absteigender Verlässlichkeit:

1. Tagesordnung: Beschlussempfehlung und Bericht eines Ausschusses. Amtlich.
2. DIP: Überweisungen je Drucksache. Amtlich.
3. Tagesordnung: Überweisungsvorschlag. Nur ein Vorschlag.
4. Textarchiv-Artikel: Hinweis auf die vorgesehene Federführung. Nur ein Vorschlag.

Der Bundestag beschließt die Überweisung erst in der ersten Beratung. Termine, die nur auf einem Vorschlag beruhen, tragen "(Ausschuss-Vorschlag)" im Titel. Nach der Überweisung ersetzt DIP den Vorschlag.

## Grenzen

- Endzeiten der Plenarpunkte und nicht öffentlicher Ausschusssitzungen sind geschätzt.
- Bei einzelnen Ausschüssen fehlen Ort oder die Angabe "öffentlich" in den Tagesordnungen. Dann bleiben die Felder leer.
- Die genutzten Schnittstellen von bundestag.de sind nicht offiziell dokumentiert und können sich ändern.
- Abonnierte Kalender werden von vielen Programmen nur alle paar Stunden aktualisiert.

## Technik

Ein Python-Skript (nur Standardbibliothek) erzeugt die Dateien, GitHub Actions führt es regelmäßig aus und veröffentlicht das Ergebnis über GitHub Pages.

- `2026-10-12_bundestag_kalender.py`: Skript
- `.github/workflows/`: Zeitplan und Veröffentlichung
- `docs/`: erzeugte Dateien (in einem Unterordner, einstellbar über die Repository-Variable `KALENDER_ORDNER`)
- `cache/`: Zwischenspeicher, damit abgeschlossene Abfragen nicht wiederholt werden

Für die Ausschuss-Zuordnung wird die DIP-API des Bundestages genutzt. Der öffentliche Schlüssel des Bundestages ist im Skript hinterlegt (gültig bis Ende Mai 2027). Ein eigener Schlüssel kann als Repository-Secret `DIP_API_KEY` eingetragen werden.
