# BorrelBeurs op de borrel — spiekbriefje

Voor de penningmeester. Alles staat in deze map; dubbelklik de `.cmd`-bestanden.
Docker Desktop moet draaien (walvis-icoon rechtsonder).

Eénmalig (de beheerder doet dit vóór de borrel): in Docker Desktop, Settings → General,
**Use containerd for pulling and storing images** aan, daarna Apply. Zonder dit vindt de
database geen image zonder internet en meldt `start.cmd` dat hier.

## Starten

1. Laptop aan, aan de lader, verbonden met het wifi van de reisrouter.
2. Dubbelklik **`start.cmd`**. De eerste keer duurt het een paar minuten.
3. Als er staat **"BorrelBeurs draait"**, zet je de getoonde link (bijvoorbeeld
   `http://192.168.8.10/`) op de telefoons en het scherm.

## Draait het nog?

Dubbelklik **`status.cmd`**. Bij `app`, `db` en `backup` hoort `running` of `Up` te staan.

## Het hangt

1. Even wachten: na een storing start de app zichzelf binnen een minuut opnieuw.
2. Nog steeds niets? Dubbelklik **`start.cmd`** nog eens. Er gaat niets verloren.
3. Helpt dat niet: dubbelklik **`logs.cmd`**, maak een foto van het scherm en bel de
   beheerder (zie onder).

## De stroom viel uit

Laptop weer aan, Docker Desktop laten opstarten, dan **`start.cmd`**. Alle bestellingen tot
het laatste "OK" op de bar-telefoon staan er nog.

## Nu een back-up maken

Dubbelklik **`backup-now.cmd`**. Er wordt sowieso elke 5 minuten automatisch een back-up
gemaakt.

## Waar staan de bestanden?

- Back-ups: `C:\BorrelBeurs\data\backups\` (`borrelbeurs-<datum>.dump`).
- Exports (Excel): `C:\BorrelBeurs\data\exports\` — elke handmatige en eindexport, plus
  elke 15 minuten automatisch (`...-auto.xlsx`).
- Na afloop: kopieer de hele map `C:\BorrelBeurs\data\` naar de USB-stick.

Terugzetten van een back-up (`restore.cmd`, typ `HERSTEL`) doe je alleen samen met de
beheerder. Mislukt het, dan blijft de app uit: probeer met de beheerder de vorige back-up
(`restore.cmd <bestandsnaam>`).

## Wie bel je wanneer?

- **Iets hangt, of de prijzen bewegen niet meer**: eerst `start.cmd`, daarna de beheerder.
- **Niets werkt en de bar moet door**: de beheerder beslist over terugvallen op de oude
  versie (v1, de map `borrelbeurs-v1-fallback` op de USB-stick). Dat kost hooguit 5 minuten.
- **Beheerder**: _naam en telefoonnummer hier invullen vóór de borrel_.
