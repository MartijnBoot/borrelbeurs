# Spec: B-01 — Settings that explain themselves

Status: Approved · Depends on: Phase 6, Phase 7 · Fixes: no open defect — closes the screen-text
side of D-21 and D-22 (both resolved in the engine in Phase 1; the labels still say the old
thing) · Backlog: [B-01](../backlog.md)

## Problem

The pricing knobs on `/settings` and `/manipulation` carry v1's names and nothing else. Coming
back after weeks, or arriving as next year's committee, nobody can tell what they do without
asking someone who remembers v1. No manual is in the repository, nor in v1's tree at tag
`v2-rebuild-complete` (only `readme.txt` and `ARCHITECTURE.md`).

**Names that say nothing.**

- ⚙️ Globale instellingen lists ten fields under v1's emoji names: "🎚️ Drempel",
  "⚔️ Rivaliteit", "🧠 Geheugen (ρ)", "📈 Na-ijlen" (`web/src/features/settings/GlobalSection.tsx:22-33`).
- The Vraag/Aanbod table heads its columns with the bare letters `a`, `d`, `s0`, `c`
  (`web/src/features/settings/DemandSection.tsx:28`, `:157-161`), and the add-drink form
  labels its fields the same way (`web/src/features/settings/DrinksSection.tsx:199-208`).
- The idle controls are half English: "Idle-decay", "Decay targets", "Rise targets"
  (`web/src/features/manipulation/IdleSection.tsx:33-43`). So are the market-event buttons:
  "💥 Market Crash", "🚀 Price Bubble" (`web/src/features/manipulation/MarketEventsSection.tsx:26-35`).
- `Field` can show one hint line under a control and nothing more (`web/src/components/ui/Field.tsx:16-34`).

**Names that are wrong.** An explanation that is wrong about the engine is worse than none.
Three of today's labels already are:

- **"🔁 Update-interval (min)"** (`GlobalSection.tsx:31`) is not how often prices update.
  `refresh_minutes` is only the clock of the idle step (`exchange/steps.py:216-219`). Orders
  move a price at once (`exchange/advance.py:53-56`), and the noise has its own clock,
  `bm_dt_minutes` (`exchange/steps.py:284-286`). This is the screen-text side of D-22.
- **"🗂️ Historie (min)"** (`GlobalSection.tsx:30`) is never read by the engine; `exchange/`
  only declares it (`exchange/spec.py:42`). It sizes the history ring that a screen's charts
  load from (`app/runtime/rehydrate.py:96`, `app/runtime/golive.py:66`) and the reconnect
  replay window (`app/realtime/hub.py:232-236`).
- **"Evenwicht, s0, auto-kalibreren bij init/reset"** (`DemandSection.tsx:145`). There is no
  reset any more (Phase 7 SD4); the anchor runs at go-live only (`app/db/runs.py:532-535`),
  and it anchors to the current prices, not to `p0` (D-21, `exchange/spec.py:155-168`).

**A value the page shows but will not save.** A first borrel starts from v1's saved settings,
`idle_decay_minutes = idle_rise_minutes = 0.1` (`app/db/runs.py:57-70`). The server accepts
only ≥ 0.5 for both (`app/runtime/config.py:106`, pinned by `tests/api/test_config.py:272`),
so a popup would have to say "Eerste borrel 0,1 · Toegestaan 0,5 of meer". The 0.5 floor has no
recorded reason (Phase 6 SD8); v1 ran live at 0.1.

## Decisions

Settled at the spec interview (2026-10-18). SD1–SD10 and SD11–SD13 were put to the owner
one at a time, each with a recommendation, and the owner chose it. The owner then delegated
("do the recommended option for further questions"): SD14 records the recommendation taken.
The planner must not reopen any of them.

- **SD1 — An (i) button that opens on tap or click; no hover.** One behaviour on phone and
  laptop. The popup closes on a second tap of the same button, a tap outside it, or Escape.
  At most one popup is open at a time. It works from the keyboard. The existing one-line
  hints ("Leeg: standaard", the jump target's bounds) stay where they are.
- **SD2 — Scope is the 33 market controls, listed in the table below.** These are the fields,
  switches, columns, target lists and buttons that change prices or what the market does.
  No (i) on the theme colours (their raw `--panel2` names stay), the image slots, the news
  level, the key roles, Borrel, Sluit app, the drink select or "Start jump".
- **SD3 — The table below is the source of truth.** The build copies each new name and
  explanation verbatim, and a test pins every one. Changing a word later is a change to this
  spec.
- **SD4 — Screen text only.** API fields, database columns, `run.params` keys, the v1
  import, the export and analytics keep their keys (`step_quant`, `lambda_orders`, …). None
  of them shows a Dutch setting name today (checked with `git grep`).
- **SD5 — "Normal value" means facts only.** Each explanation gives:
  - the start value (worded per SD14): `DEFAULT_PARAMS` (`app/db/runs.py:57-70`), else
    `Params()`'s default (`exchange/spec.py:32-58`); the candle interval's 60 s (Phase 6
    SD2); the two durations' form defaults; and for a drink the add-drink defaults (Phase 6
    SD5);
  - the allowed range (`app/runtime/config.py:98-133`, Phase 6 SD5/SD8/SD22/SD23, and SD9
    below);
  - where it matters, when the setting does nothing.

  Nothing like "0,5–1,5 voelt rustig": that is not in the code, and B-03/B-04 exist because
  the feel is still being found.
- **SD6 — Section headings stay as they are.** ⚙️ Globale instellingen, ⏳ Idle,
  💥 Market events and the rest keep their emoji and wording; B-02 owns emoji. The 33
  controls' new names have no emoji. That includes the market-event buttons, whose new names
  match their existing confirmations ("Marktcrash starten?", "Terug naar start?",
  "Prijsbubbel starten?", which stay unchanged).
- **SD7 — A "Tijdens de borrel" line only where a live change does more than apply from the
  next step.** That is Prijsstap, the three bounds, Normale barprijs, Grafiekgeschiedenis,
  Kaarsbreedte and Evenwicht zetten bij live zetten (Phase 6 SD9, SD10, PD18; Phase 7 T2).
  Evenwicht op huidige prijzen says it is live-only in its first line.
- **SD8 — Two guards keep the texts true.**
  1. A test fails when a start value or range quoted in an explanation no longer matches the
     code it came from.
  2. `.claude/agents/engine-guardian.md` gains one checklist line: when a diff touches
     `exchange/`, re-check the rows of this table that cite the changed lines. This is a
     `.claude/` edit, so the owner commits it.
- **SD9 — The idle-time floor drops to 0.1.** `idle_decay_minutes` and `idle_rise_minutes`
  accept ≥ 0.1, so v1's saved 0.1 can be saved again. This is a validation change in
  `ParamsPatch`, not a maths change. It supersedes that row of Phase 6 SD8, and the Phase 6
  spec gets a note saying so.
- **SD10 — The manual is out of scope.** It is not in the repository. Updating or retiring
  it is the owner's business once the popups exist.

**After `engine-guardian`'s check of the drafted table (2026-10-18)**

The guardian found every start value and range right, and these claims wrong or imprecise.
Plain factual slips were corrected directly (E1, E6–E12, E20, E21, E23, E31). The following
changed what the room is told the maths does, so they were the owner's:

- **SD11 — Off-grid bounds are told, not forbidden.** The quote is rounded to the Prijsstap,
  so with Minimumprijs 1,24 on a 0,10 step it sits at 1,20, and the unstick rule
  (`exchange/steps.py:113-130`) never fires, so a crashed drink stays on the floor. E17 and
  E19 say so and advise a bound on the grid. Requiring on-grid bounds is
  [B-07](../backlog.md), not this item.
- **SD12 — Events and jumps are described as they look.** The smoothstep runs in `y`, and a
  bound target is `y ≈ ±20,7`. A crash or bubble therefore reaches its bound after roughly a
  third of the duration and then holds, and a correction straight after one lingers at the
  bound. E27–E32 say so, with "meestal" and "ongeveer", because the fraction depends on where
  a drink starts. v1's maths, unchanged.
- **SD13 — Concurrentie tussen drankjes covers demand on and off.** Rivalry acts on the
  difference from expected sales (`exchange/steps.py:83-89`). With Verwachte verkoop
  meetellen on, it usually pushes the drinks that were not ordered *up*. E4 adds one sentence
  for that case rather than being true only with demand off.
- **SD14 — "Eerste borrel", not "Standaard", for a run parameter's start value.** Only the
  first borrel starts from `DEFAULT_PARAMS`; every later one copies the previous run's
  params (`app/db/runs.py:458`). So E1–E9, E11, E12 and E21–E26 read "Eerste borrel: …".
  Kaarsbreedte (60 for every new borrel) and the two durations (the form's default) keep
  "Standaard". The drink fields keep "Leeg bij toevoegen".

## The table

Each row gives the field, where it appears, its v1 label, its **new name**, and the
explanation. The explanation is shown verbatim: one paragraph per line below, in this order:
what it does; then *Hoger/Lager* (a number), *Aan/Uit* (a switch) or *Je ziet* (a button);
then *Eerste borrel*, *Standaard* or *Leeg bij toevoegen* (SD14), and *Toegestaan*; then *Tijdens de borrel* where
SD7 asks for it. The popup's title is the new name. A name in an explanation always refers to
another control by its new name. **Bron** is the code the claims rest on, for SD8's re-check;
it is not shown.

Numbers use the Dutch decimal comma. "Toegestaan" ranges are the server's.

### Globale instellingen (`/settings`)

**E1 — `step_quant`.** Was "🧱 Tickgrootte". **Prijsstap (€)**

> De prijs op het bord en aan de bar is altijd een veelvoud van dit bedrag. De grafieken lopen per cent en kunnen tussen de stappen door bewegen. Ook de Doelprijs van een sprong wordt hierop afgerond.
> Hoger: grotere stappen, en een prijs blijft vaker even staan. Lager: fijnere bewegingen.
> Eerste borrel: 0,10. Toegestaan: meer dan 0 en hoogstens 5, in hele centen.
> Tijdens de borrel: elke koers blijft staan, afgerond op de nieuwe stap en binnen Minimumprijs en Maximumprijs. Alle lopende prijssprongen stoppen, ook die van een marktgebeurtenis; de melding van een marktgebeurtenis blijft staan.

Bron: `exchange/pricing.py:32-42`, `exchange/steps.py:161-162`, `app/runtime/candles.py:1-6`, `:83`, `app/runtime/config.py:433-456`, `exchange/state.py:104-130`.

**E2 — `eta`.** Was "⚡ Snelheid". **Beweging per bestelling**

> Hoe groot de volle beweging van een prijs is bij één bestelling of één duwtje bij stilte. Hoeveel druk daarvoor nodig is, bepaalt Drukdrempel. Vlak bij de Minimumprijs of Maximumprijs beweegt een prijs minder ver.
> Hoger: prijzen reageren heftiger. Lager: rustiger.
> Eerste borrel: 0,8. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:96-102`, `exchange/pricing.py:36-42`.

**E3 — `K`.** Was "🎚️ Drempel". **Drukdrempel**

> Hoeveel druk nodig is voor de volle beweging van Beweging per bestelling. De druk komt vooral van het aantal stuks in één bestelling.
> Lager: één drankje geeft al bijna de volle beweging, en een grote ronde doet weinig extra. Hoger: een los drankje beweegt de prijs weinig, een grote ronde veel meer.
> Eerste borrel: 5. Toegestaan: meer dan 0.

Bron: `exchange/steps.py:83-94`, `:102`.

**E4 — `lambda_orders`.** Was "⚔️ Rivaliteit". **Concurrentie tussen drankjes**

> Bij elke bestelling gaan de andere drankjes iets omlaag. Het effect wordt over die andere drankjes verdeeld: hoe meer drankjes, hoe minder elk afzonderlijk zakt. Een duwtje bij stilte werkt andersom: zakt een stil drankje, dan gaan de andere iets omhoog. Met Verwachte verkoop meetellen aan telt het verschil met de verwachte verkoop: verkopen de andere drankjes minder dan verwacht, dan duwt dit ze juist omhoog.
> Hoger: een bestelling drukt de andere prijzen sterker. 0: een bestelling duwt de andere drankjes niet meer rechtstreeks.
> Eerste borrel: 1,5. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:83-89`, `:267`.

**E5 — `alpha_price`.** Was "🧭 Aantrekking naar gemiddelde". **Trek naar gemiddelde prijs**

> Bij elke bestelling en elk duwtje bij stilte trekt dit dure drankjes iets omlaag en goedkope iets omhoog, naar de gemiddelde prijs van alle drankjes.
> Hoger: de prijzen blijven dichter bij elkaar. 0: uit.
> Eerste borrel: 0 (uit). Toegestaan: 0 of meer.

Bron: `exchange/steps.py:76`, `:92-94`.

**E6 — `phi_persist`.** Was "📈 Na-ijlen". **Nawerking van bestellingen**

> Eerdere bestellingen blijven doorduwen. Een drankje dat veel besteld is, krijgt bij elke volgende bestelling en elk duwtje bij stilte een extra duw omhoog, ook als het zelf niet besteld wordt. Een drankje dat duwtjes omlaag bij stilte kreeg (of, met Verwachte verkoop meetellen aan, minder verkocht dan verwacht) krijgt een extra duw omlaag. Wat Concurrentie tussen drankjes doet, wordt niet onthouden. Hoe lang het doorduwen duurt, bepaalt Geheugen van bestellingen.
> Hoger: trends houden sterker aan. 0: alleen de bestelling zelf telt.
> Eerste borrel: 0,1. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:83`, `:91-94`, `:267`.

**E7 — `decay_rho`.** Was "🧠 Geheugen (ρ)". **Geheugen van bestellingen**

> Hoeveel van de opgebouwde Nawerking van bestellingen overblijft bij elke volgende bestelling of elk duwtje bij stilte; de rest wordt vergeten. Het vergeten telt per bestelling, niet per minuut: in een stille periode zonder duwtjes vergeet de markt niets. Doet niets als Nawerking van bestellingen 0 is.
> Hoger (naar 1): bestellingen werken lang door. Lager: de markt vergeet snel. 1: nooit vergeten. 0: meteen vergeten.
> Eerste borrel: 0,98. Toegestaan: 0 tot en met 1.

Bron: `exchange/steps.py:91`, `:267`; `exchange/advance.py:53-59` (only order and idle steps run `_single_step`).

**E8 — `history_window_minutes`.** Was "🗂️ Historie (min)". **Grafiekgeschiedenis (min)**

> Hoeveel minuten koersverloop een scherm meekrijgt als het opent of opnieuw verbindt. Een scherm dat open blijft, tekent daarna gewoon door. Heeft geen invloed op de prijzen.
> Hoger: langere grafieken na openen of herladen. Lager: kortere.
> Eerste borrel: 15. Toegestaan: 1 tot en met 240.
> Tijdens de borrel: korter geldt meteen; langer vult zich pas aan naarmate de borrel verder loopt.

Bron: `exchange/spec.py:42` (declared, never read in `exchange/`), `app/runtime/history.py:26-30`, `:56-60`, `app/runtime/rehydrate.py:96`, `app/realtime/hub.py:232-236`.

**E9 — `refresh_minutes`.** Was "🔁 Update-interval (min)". **Ritme stille drankjes (min)**

> Om de zoveel minuten kijkt de beurs of drankjes uit Omlaag bij stilte of Omhoog bij stilte een duwtje krijgen; alleen op die momenten. Dit is niet hoe vaak de prijzen verversen: een bestelling beweegt een prijs meteen, en de ruis loopt op een eigen klok. Zonder drankjes in Omlaag bij stilte of Omhoog bij stilte doet dit niets.
> Hoger: minder vaak een duwtje. Lager: vaker, dus samen sterker.
> Eerste borrel: 0,2 (elke 12 seconden). Toegestaan: 0,1 tot en met 10.

Bron: `exchange/steps.py:205-219` (D-22), `exchange/advance.py:53-59`, `exchange/steps.py:284-286`.

**E10 — `candle_interval_s`.** Was "🕯️ Kaarseninterval (sec)". **Kaarsbreedte (sec)**

> Hoeveel seconden één kaars in de koersgrafieken beslaat. Heeft geen invloed op de prijzen.
> Hoger: minder, bredere kaarsen. Lager: meer, smallere.
> Standaard: 60. Toegestaan: 5 tot en met 3600, in veelvouden van 5.
> Tijdens de borrel: alle grafieken op het koersbord worden meteen opnieuw getekend, over de laatste Grafiekgeschiedenis.

Bron: `app/runtime/candles.py:83`, Phase 6 SD10 / AC28.

### Vraag/Aanbod (`/settings`)

**E11 — `demand_enabled`.** Was "Vraag/aanbod actief". **Verwachte verkoop meetellen**

> Aan: bij elke bestelling vergelijkt de beurs wat elk drankje in die bestelling verkocht met wat bij zijn prijs verwacht wordt (Basisvraag, Prijsgevoeligheid, Vraagverschuiving en Voordeel onder gemiddelde). Minder dan verwacht duwt de prijs omlaag, meer duwt hem omhoog. Drankjes die niet in de bestelling zitten, tellen als niets verkocht: wordt er voor hen verkoop verwacht, dan zakken ze. Dat gebeurt ook bij elk duwtje bij stilte, voor alle drankjes. Bij stilte duwt Kracht omlaag of Kracht omhoog bovendien harder bij drankjes waar veel verkoop verwacht wordt.
> Uit: alleen de bestellingen zelf tellen; de vier kolommen doen niets.
> Eerste borrel: uit.

Bron: `exchange/steps.py:77-83`, `:227-231`, `:246-248`; `exchange/pricing.py:45-61`.

**E12 — `auto_calibrate_s0`.** Was "Evenwicht, s0, auto-kalibreren bij init/reset". **Evenwicht zetten bij live zetten**

> Aan: bij Live zetten krijgt elk drankje een Vraagverschuiving (s0) waarbij de verwachte verkoop op zijn startprijs (afgerond op de Prijsstap) precies nul is, zoals Evenwicht op huidige prijzen dat later tijdens de borrel doet. Een drankje dat je tijdens de borrel toevoegt, houdt zijn ingevulde Vraagverschuiving. Uit: de Vraagverschuiving blijft zoals ingevuld. Op de prijzen werkt het alleen als Verwachte verkoop meetellen aan staat.
> Eerste borrel: uit.
> Tijdens de borrel: verandert niets meer; dit gebeurt alleen bij Live zetten.

Bron: `app/db/runs.py:529-535`, `exchange/spec.py:155-168` (D-21), `exchange/state.py:79`.

**E13 — `a`** (table column, add-drink form). Was "a". **Basisvraag (a)**

> De verkoop die bij elke bestelling voor dit drankje verwacht wordt, los van zijn prijs. De verwachte verkoop is nooit minder dan 0. Telt alleen als Verwachte verkoop meetellen aan staat.
> Hoger: dit drankje moet meer verkopen om niet te zakken.
> Leeg bij toevoegen: 10. Toegestaan: elk getal.

Bron: `exchange/pricing.py:59-61`, `exchange/steps.py:83`.

**E14 — `d`** (table column, add-drink form). Was "d". **Prijsgevoeligheid (d)**

> Hoeveel de verwachte verkoop daalt voor elke euro die dit drankje kost. Telt alleen als Verwachte verkoop meetellen aan staat.
> Hoger: wordt het drankje duurder, dan verwacht de beurs snel minder verkoop, dus zakt het minder als niemand het bestelt.
> Leeg bij toevoegen: 0,6. Toegestaan: elk getal.

Bron: `exchange/pricing.py:59-61`.

**E15 — `s0`** (table column, add-drink form). Was "s0". **Vraagverschuiving (s0)**

> Telt op bij de verwachte verkoop, net als Basisvraag. Evenwicht op huidige prijzen en Evenwicht zetten bij live zetten vullen hem zo in dat de verwachte verkoop bij de huidige prijs precies nul is. Telt alleen als Verwachte verkoop meetellen aan staat.
> Hoger: meer verwachte verkoop.
> Leeg bij toevoegen: 8. Toegestaan: elk getal.

Bron: `exchange/pricing.py:59-61`, `exchange/spec.py:165-168`.

**E16 — `c`** (table column, add-drink form). Was "c". **Voordeel onder gemiddelde (c)**

> Hoeveel extra verkoop verwacht wordt voor elke euro dat dit drankje goedkoper is dan het gemiddelde van alle drankjes; duurder dan gemiddeld geeft zoveel minder. Telt alleen als Verwachte verkoop meetellen aan staat.
> Hoger: de beurs verwacht dat goedkope drankjes veel beter lopen.
> Leeg bij toevoegen: 0,4. Toegestaan: elk getal.

Bron: `exchange/pricing.py:59-61`, `exchange/steps.py:76`.

### Min/Max/Startprijs and Drankjes beheren (`/settings`)

E17–E20 appear wherever the field does: the Min/Max/Startprijs rows, the add-drink form and,
for E20, the drink row.

**E17 — `p_min_cents`.** Was "Min". **Minimumprijs (€)**

> De koers van dit drankje komt nooit lager dan de Minimumprijs, afgerond op de Prijsstap. Kies hem als veelvoud van de Prijsstap: anders kan de koers tot een halve stap eronder uitkomen en na een Marktcrash lang op de bodem blijven hangen. Een Marktcrash zakt hierheen. Hoe dichter een prijs bij de Minimumprijs of Maximumprijs, hoe minder ver hij per stap beweegt.
> Toegestaan: 0 of meer, en lager dan de Startprijs.
> Tijdens de borrel: de huidige koers blijft staan, binnen de nieuwe grenzen en op de Prijsstap. Een lopende prijssprong op dit drankje stopt, ook die van een marktgebeurtenis.

Bron: `exchange/pricing.py:32-42`, `exchange/steps.py:96-100`, `:113-130` (the unstick check needs the quote exactly on the bound), `app/runtime/market_events.py:47-53`, `exchange/state.py:104-130`; measured by `engine-guardian` 2026-10-18 (Minimumprijs 1,24 at step 0,10 quotes 1,20).

**E18 — `p0_cents`.** Was "Start". **Startprijs (€)**

> De prijs waarmee dit drankje begint: bij Live zetten, of meteen als je het tijdens de borrel toevoegt. Terug naar startprijs gaat hierheen.
> Toegestaan: hoger dan de Minimumprijs en lager dan de Maximumprijs.
> Tijdens de borrel: de huidige koers verandert niet; alleen Terug naar startprijs gebruikt de nieuwe waarde.

Bron: `exchange/state.py:79`, `:169`; `app/runtime/market_events.py:47-53`; Phase 6 SD9.

**E19 — `p_max_cents`.** Was "Max". **Maximumprijs (€)**

> De koers van dit drankje komt nooit hoger dan de Maximumprijs, afgerond op de Prijsstap. Kies hem als veelvoud van de Prijsstap: anders kan de koers tot een halve stap erboven uitkomen en na een Prijsbubbel lang aan de top blijven hangen. Een Prijsbubbel stijgt hierheen. Hoe dichter een prijs bij de Minimumprijs of Maximumprijs, hoe minder ver hij per stap beweegt.
> Toegestaan: hoger dan de Startprijs.
> Tijdens de borrel: de huidige koers blijft staan, binnen de nieuwe grenzen en op de Prijsstap. Een lopende prijssprong op dit drankje stopt, ook die van een marktgebeurtenis.

Bron: as E17.

**E20 — `bar_price_cents`.** Was "Barprijs". **Normale barprijs (€)**

> Wat dit drankje normaal aan de bar kost. Alleen gebruikt om de omzet te vergelijken: "Omzet tegen barprijs" in de analyse, en in de export. De koers merkt er niets van.
> Leeg bij toevoegen: de Startprijs. Toegestaan: 0 of meer.
> Tijdens de borrel: geldt voor verkopen vanaf nu; eerdere verkopen houden hun barprijs.

Bron: D-20 / Phase 7 T2 (stored per sale), `web/src/features/analytics/RunDetail.tsx:52`, Phase 6 SD9.

### Idle (`/manipulation`, admin)

**E21 — `idle_decay_minutes`.** Was "🕒 Idle-decay (min)". **Omlaag na stilte van (min)**

> Een drankje uit Omlaag bij stilte dat minstens zo lang niet besteld is, krijgt op elk moment van Ritme stille drankjes een duwtje omlaag, zolang het niet besteld wordt. Het eerste duwtje kan dus iets later komen. Nog nooit besteld telt vanaf Live zetten, of vanaf het toevoegen.
> Hoger: pas na een langere stilte.
> Eerste borrel: 0,1. Toegestaan: 0,1 of meer.

Bron: `exchange/steps.py:216-219`, `:239-249`; `exchange/state.py:82`, `:169`; SD9.

**E22 — `idle_strength`.** Was "⬇️ Decay-sterkte". **Kracht omlaag**

> Hoe hard elk duwtje omlaag is. Het werkt als een bestelling met een minteken: door Concurrentie tussen drankjes gaan de andere drankjes daarbij iets omhoog, en Nawerking van bestellingen onthoudt het. Met Verwachte verkoop meetellen aan duwt het harder bij drankjes waar veel verkoop verwacht wordt.
> Hoger: stille drankjes zakken sneller.
> Eerste borrel: 1,5. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:246-249`, `:267`, `:83-91`.

**E23 — `idle_rise_minutes`.** Was "🕒 Idle-rise (min)". **Omhoog na stilte van (min)**

> Een drankje uit Omhoog bij stilte dat minstens zo lang niet besteld is, krijgt op elk moment van Ritme stille drankjes een duwtje omhoog, zolang het niet besteld wordt. Het eerste duwtje kan dus iets later komen. Nog nooit besteld telt vanaf Live zetten, of vanaf het toevoegen.
> Hoger: pas na een langere stilte.
> Eerste borrel: 0,1. Toegestaan: 0,1 of meer.

Bron: `exchange/steps.py:216-219`, `:252-262`; `exchange/state.py:82`, `:169`; SD9.

**E24 — `idle_rise_strength`.** Was "⬆️ Rise-sterkte". **Kracht omhoog**

> Hoe hard elk duwtje omhoog is. Het werkt als een bestelling: door Concurrentie tussen drankjes gaan de andere drankjes daarbij iets omlaag, en Nawerking van bestellingen onthoudt het. Met Verwachte verkoop meetellen aan duwt het harder bij drankjes waar veel verkoop verwacht wordt.
> Hoger: stille drankjes stijgen sneller.
> Eerste borrel: 1,5. Toegestaan: 0 of meer.

Bron: `exchange/steps.py:259-262`, `:267`, `:83-91`.

**E25 — `idle_targets`** (the checkbox group's legend). Was "Decay targets". **Omlaag bij stilte**

> De drankjes die een duwtje omlaag krijgen als ze een tijd niet besteld zijn (Omlaag na stilte van, Kracht omlaag). Staat een drankje ook in Omhoog bij stilte, dan werken de duwtjes tegen elkaar in.
> Eerste borrel: geen drankjes.

Bron: `exchange/steps.py:222-223`, `:239-262`.

**E26 — `idle_rise_targets`** (the checkbox group's legend). Was "Rise targets". **Omhoog bij stilte**

> De drankjes die een duwtje omhoog krijgen als ze een tijd niet besteld zijn (Omhoog na stilte van, Kracht omhoog). Staat een drankje ook in Omlaag bij stilte, dan werken de duwtjes tegen elkaar in.
> Eerste borrel: geen drankjes.

Bron: as E25.

### Market events (`/manipulation`)

**E27 — event duration.** Was "Duur (seconden)". **Duur gebeurtenis (sec)**

> Hoe lang Marktcrash, Terug naar startprijs en Prijsbubbel de prijzen vasthouden, en hoe lang het koersbord de melding toont. Bij Marktcrash en Prijsbubbel staan de prijzen meestal al na ongeveer een derde van deze tijd op hun grens, en blijven ze daar tot het eind. Direct na een Marktcrash of Prijsbubbel blijft Terug naar startprijs juist lang bij de grens en komt pas tegen het eind terug. Bestellingen in die tijd tellen wel mee voor Nawerking van bestellingen, en duwen daarna door.
> Standaard: 30. Toegestaan: 1 tot en met 600.

Bron: `app/runtime/manipulation.py:120-190`, `app/api/market.py:45`, Phase 6 SD22; the easing runs in `y`, and a target on a bound is `y ≈ ±20,7` (`exchange/steps.py:164-165`, `:196-200`, Phase 1 plan R8); measured by `engine-guardian` 2026-10-18 (bounds 1–3, start 2, 30 s crash: 1,70 at 10 %, 1,20 at 20 %, 1,00 at 30 %).

**E28 — the crash button.** Was "💥 Market Crash". **Marktcrash**

> Je ziet: alle drankjes zakken snel naar hun Minimumprijs en staan daar meestal al na ongeveer een derde van de Duur gebeurtenis. Het koersbord toont de crashmelding en er verschijnt een nieuwsbericht. Tot het eind van de Duur gebeurtenis verschuiven bestellingen deze prijzen niet, maar Nawerking van bestellingen onthoudt ze wel. Een lopende marktgebeurtenis of prijssprong wordt vervangen.

Bron: `app/runtime/market_events.py:38-53`, `app/runtime/manipulation.py:120-150`, `exchange/steps.py:164-165`, `:174-202`, `exchange/advance.py:53-59`; the measurement under E27.

**E29 — the correction button.** Was "🔄 Terug naar start". **Terug naar startprijs**

> Je ziet: alle drankjes glijden in de Duur gebeurtenis terug naar hun Startprijs. Direct na een Marktcrash of Prijsbubbel blijven ze eerst lang bij hun grens en komen ze pas tegen het eind terug. Het koersbord toont een rustige melding en er verschijnt een nieuwsbericht. Zolang ze glijden, verschuiven bestellingen deze prijzen niet, maar Nawerking van bestellingen onthoudt ze wel. Een lopende marktgebeurtenis of prijssprong wordt vervangen.

Bron: as E28; Phase 6 AC42 (the calm banner).

**E30 — the bubble button.** Was "🚀 Price Bubble". **Prijsbubbel**

> Je ziet: alle drankjes stijgen snel naar hun Maximumprijs en staan daar meestal al na ongeveer een derde van de Duur gebeurtenis. Het koersbord toont de bubbelmelding en er verschijnt een nieuwsbericht. Tot het eind van de Duur gebeurtenis verschuiven bestellingen deze prijzen niet, maar Nawerking van bestellingen onthoudt ze wel. Een lopende marktgebeurtenis of prijssprong wordt vervangen.

Bron: as E28.

### Price jump (`/manipulation`)

**E31 — the jump target.** Was "Doelprijs (€)". **Doelprijs (€)** (unchanged)

> De prijs waar dit drankje naartoe glijdt, afgerond op de Prijsstap. Moet tussen de Minimumprijs en de Maximumprijs liggen. Zolang het glijdt, verschuiven bestellingen de prijs niet; ze tellen wel mee voor Nawerking van bestellingen en Concurrentie tussen drankjes. Een Doelprijs op de Minimumprijs of Maximumprijs wordt al ruim voor het eind bereikt.
> Toegestaan: van de Minimumprijs tot en met de Maximumprijs van dit drankje.

Bron: `exchange/steps.py:141-177`, `:180-202`; Phase 6 SD23.

**E32 — the jump duration.** Was "Duur (seconden)". **Duur sprong (sec)**

> Hoe lang het glijden naar de Doelprijs duurt, langzaam beginnend en langzaam eindigend. Ligt de Doelprijs op de Minimumprijs of Maximumprijs, dan is hij er al ruim voor het eind. Een nieuwe sprong op hetzelfde drankje vervangt de lopende.
> Standaard: 5. Toegestaan: 1 tot en met 1800.

Bron: `exchange/steps.py:166-177`, `:196-199`; `app/api/market.py:34`.

### Systeemacties (`/settings`)

**E33 — the anchor button.** Was "📌 Zet huidige prijs als evenwicht". **Evenwicht op huidige prijzen**

> Werkt alleen tijdens een live borrel. Geeft elk drankje een Vraagverschuiving (s0) waarbij de verwachte verkoop bij zijn huidige koers precies nul is. Er beweegt geen prijs.
> Je ziet: niets op het koersbord. Op de prijzen werkt het pas als Verwachte verkoop meetellen aan staat.

Bron: `app/runtime/config.py:465-476`, `exchange/spec.py:155-168`, Phase 6 SD9.

## In scope

- **Web:**
  - an (i) button and popup component in `components/ui`, and a way for `Field`,
    `NumberField`, `MoneyField`, `Switch`, a table column header, a fieldset legend and a
    `Button` to carry one (SD1);
  - the 33 new names and explanations in `features/settings` (Global, Demand, Bounds, Drinks,
    System) and `features/manipulation` (Idle, MarketEvents, PriceJump), verbatim from the
    table;
  - the bounds row's client-side error "Min < Start < Max" (`BoundsSection.tsx:85`) becomes
    "Minimumprijs < Startprijs < Maximumprijs";
  - every test and e2e selector that names an old label (`GlobalSection.test.tsx`,
    `IdleSection.test.tsx`, `DemandSection.test.tsx`, `web/e2e/admin.spec.ts`, …).
- **Server:** the idle-minutes floor 0.5 → 0.1 in `app/runtime/config.py` (SD9), its test
  (`tests/api/test_config.py:272`), and the OpenAPI types regenerated if the schema changes.
- **The SD8 guards:** the start-value/range test, and the `engine-guardian` checklist line
  (owner-committed).
- **Documents:**
  - a note on Phase 6 SD8 (`docs/specs/phase-6-admin.md:182-197`): the labels and the
    idle-minutes floor are superseded by this spec;
  - B-01's backlog status.

## Out of scope

- Any change to the pricing maths, to a default, or to what a setting does. `exchange/` is
  read, never changed. The one exception is SD9's validation floor, which is not maths.
- Renaming any API field, database column, `run.params` key, export column or v1-import
  key (SD4).
- Section headings, sidebar entries and page titles (SD6). Emoji anywhere outside the 33 names
  (B-02).
- An (i) on anything outside the 33: theme colours, images, news, keys, Borrel, Sluit app, the
  drink select, "Start jump", the save buttons (SD2).
- The theme editor's raw token names (`--panel2`, …): a later backlog item, if wanted.
- Hover popups, a help page, an in-app manual, links to documentation, or the external manual
  (SD1, SD10).
- Experience-based advice ("normal feels like…") or worked examples with numbers (SD5).
- Editing `bm_*`, `flow_vol_amp`, `flow_beta`, `y_clip` (B-03); setting profiles (B-04).
- Explanations in any language but Dutch; changing the confirmation texts or the
  "{crash|reset|bubble} gestart!" status.
- Changing a range other than SD9's, or `DEFAULT_PARAMS`.

## Acceptance criteria

**The popup — SD1**

- **AC1.** When the (i) next to any of the 33 controls is tapped or clicked, the system shall
  open a popup titled with the control's new name, showing its explanation from the table.
  When the same (i) is tapped again, the user taps outside, or Escape is pressed, the system
  shall close it.
- **AC2.** While one popup is open, when another (i) is opened, the system shall close the
  first. At most one popup shall be open.
- **AC3.** When the pointer only hovers over an (i), the system shall not open a popup.
- **AC4.** When the (i) is reached by keyboard, Enter or Space shall open it. On close, focus
  shall return to the (i). The (i) shall have the accessible name "Uitleg: {new name}" and
  `aria-expanded` reflecting its state.
- **AC5.** When an (i) inside a form is activated, the system shall not submit the form,
  change the control's value, or mark its section dirty.
- **AC6.** At a 360 px wide viewport, every popup shall be fully visible without horizontal
  scrolling.

**Names and texts — SD2, SD3, SD6**

- **AC7.** Each of the 33 controls shall carry exactly its new name from the table as its
  visible label or button text, and as its accessible name. For a table cell, the accessible
  name is "{drink} {new name}". Each popup shall carry its explanation exactly, one paragraph
  per line of the table. A test shall pin every name and text against the table.
- **AC8.** No new name shall contain an emoji. Every section heading shall be unchanged.
- **AC9.** Wherever a field appears more than once (E13–E20 in the table, the add-drink form,
  the bounds rows and the drink row), it shall carry the same name and the same explanation.
- **AC10.** No control outside the 33 shall gain an (i).
- **AC11.** No API request body, response, database value or export shall change because of
  this item, except SD9's floor.

**The two wrong labels — D-21, D-22**

- **AC12.** The control for `refresh_minutes` shall be named "Ritme stille drankjes (min)",
  and its explanation shall say that it sets the moments of the idle push and is not how often
  prices update. *(D-22)*
- **AC13.** The control for `auto_calibrate_s0` shall not mention "init" or "reset", and
  shall say that it acts at Live zetten only. The anchor button's explanation shall say it
  anchors on the *current* prices. *(D-21)*

**Truth guards — SD5, SD8**

- **AC14.** Every "Eerste borrel", "Standaard" and "Leeg bij toevoegen" value in an
  explanation shall equal the code's value: `DEFAULT_PARAMS`, else `Params()`, for "Eerste
  borrel"; 60 for the candle interval; the add-drink defaults; 30 and 5 for the two
  durations. When one of those values changes, a test shall fail until the explanation
  changes. A run parameter's start value shall be labelled "Eerste borrel", never
  "Standaard" (SD14).
- **AC15.** Every "Toegestaan" range shall equal the server's validation for that field. When
  a range changes, a test shall fail until the explanation changes.
- **AC16.** `.claude/agents/engine-guardian.md` shall tell the guardian to re-check this
  table's rows whose Bron cites lines a diff changes.

**The idle-minutes floor — SD9**

- **AC17.** When `idle_decay_minutes` or `idle_rise_minutes` is sent as 0.1, the server shall
  accept and store it. When either is sent below 0.1, it shall return 422 naming the field.
- **AC18.** When the Idle section shows a run started from `DEFAULT_PARAMS`, and only another
  field is edited and saved, the save shall succeed.

**No maths change**

- **AC19.** `exchange/` shall be unchanged by this item, and the golden fixtures shall replay
  unchanged.

## Verification

- **Before approval:** `engine-guardian` reads the table against each row's Bron and
  reports. Any row it doubts goes to the owner, never to the builder.
- **Vitest / component tests:**
  - the popup: open on click, close on second click, outside click and Escape; one at a time;
    no open on hover; keyboard open and focus return; no submit and no dirty (AC1–AC5);
  - every one of the 33 names and texts, read from one table in the source and asserted per
    section, including the add-drink form and the table's column headers (AC7, AC9);
  - no emoji in any name; section headings unchanged (AC8);
  - the controls without an (i) (AC10);
  - the old labels' tests, rewritten to the new names, still pass on the same behaviour.
- **The guard test (pytest or Vitest; the planner chooses):** each quoted start value and range
  against `DEFAULT_PARAMS` / `Params()`, `ParamsPatch` and the drink, event and jump
  validators (AC14, AC15). Proved by temporarily changing one default and one range and seeing
  it fail.
- **API (pytest):** idle minutes 0.1 accepted, 0.09 rejected with the field named (AC17).
- **Playwright (in the gate):** at a 360 px viewport, open the (i) of Prijsstap on `/settings`
  and of Kracht omlaag on `/manipulation`. Each popup is fully visible and closes on Escape
  (AC6). Saving Globale instellingen through the new labels still works (the old
  `Tickgrootte` step in `web/e2e/admin.spec.ts`).
- **The gate:** `./scripts/check.sh` green; `bash scripts/golden_linux.sh` green, since
  `exchange/` must not move (AC19).
- **Manual (exit check):** someone who has not seen the pages reads every popup on a phone and
  answers, without the manual: which setting makes other drinks drop when one is ordered,
  which one stops a drink from going lower, and what happens to prices when the Kaarsbreedte
  changes.

## Exit condition

Every market control on `/settings` and `/manipulation` has a name that says what it does and
a tap-to-open explanation that matches the engine, and a test fails if a quoted default or
range drifts from the code.
