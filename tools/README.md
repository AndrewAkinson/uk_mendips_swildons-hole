# Tools for continuing the resurvey

How to get a new SexyTopo trip (or an old PocketTopo one) into the
survey, with drawings. The converter and the drawing rules are shared
with other caves: `sketch2therion/` is a link to a clone of
[CaveSurveying/Therion-Sketching](https://github.com/CaveSurveying/Therion-Sketching),
and its `Style.md` is the one place the drawing conventions are kept.

| Path | What it is |
|---|---|
| `sketch2therion/` | The shared tools. Converts SexyTopo and PocketTopo sketches into Therion drawings (`.th2`) and checks them (`review`, `fillcheck`, `th2lint`). |
| `sketch2therion/Style.md`, `sketch2therion/rules.toml` | The shared drawing rules. |
| `project.toml` | Swildons' settings for the shared tools: the master file, the plan map, file and scrap names. A `[convert]` table there changes a shared rule for Swildons only, with the reason. |
| `layout.thconfig`, `layout.th` | Export where Therion puts every station, and the centreline with its splays, for the converter. |
| `sections/` | Swildons only: points the cross section lines the way each section looks, and moves section drawings clear of the passages on the Swildons sheets. |
| `new-trip-template.th` | A starting point for a new trip's survey file. |
| `requirements.txt` | Python libraries (the shared tools' own list). |

The plans from below the 20 ft Pot to Sump 1, and all the elevations
and cross sections, were made from Footleg's PocketTopo sketches with
an earlier version of the converter. Tratman's Temple (`Tratmans/`,
2026) is the first survey drawn with the shared tools. The output is a
faithful first draft, not a finished drawing. Expect to tidy it in
xTherion.

## Setting up

`sketch2therion` links to `../../Therion-Sketching`. Clone that
repository in the same folder as this one, so the link finds it:

```bash
git clone https://github.com/CaveSurveying/Therion-Sketching.git
```

Every cave uses whatever is checked out there, so keep it up to date
with `git pull`. The first note in each drawing gives the converter
commit that made it.

You need Python 3.11 or later with the libraries in `requirements.txt`,
and Therion (Docker is easiest, as in the main
[README](../README.md#building-it-yourself)):

```bash
pip install -r tools/requirements.txt
therion() { docker run --rm -v "$PWD:/project" \
  -e PROJ_DATA=/project/proj:/usr/share/proj -e PROJ_NETWORK=OFF \
  ghcr.io/paperclipmonkey/therion:6.4.0 "$@"; }
```

Run everything from the top of the repository.

## Underground, in SexyTopo

Sketch as `sketch2therion/Style.md` says ("Sketching in SexyTopo"):
the colours the converter reads, cross sections, and drawing both the
plan and the extended elevation. Note in the book which existing
station the trip starts from.

## After the trip

Tratman's Temple is the example here: the survey `Tratmans`, in
`Tratmans/`.

1. **Export** from SexyTopo into the survey's own folder: `X.th`, and
   the sketches in `X/Notes/` (`XP.xvi` for the plan, `XEE.xvi` for the
   extended elevation).

2. **Tie it in** in `swildonsmaster.th`: `input X/X.th`, and an
   `equate` from the trip's first station to the one it started from,
   e.g. `equate 1@Tratmans 23.33@BarnesLoopToTratmans.Swildons`. Add
   the survey to the `ResurveyCentreline` map there, so its legs appear
   on the centreline sheets. Build
   (`therion -l output/therion.log swildons.thconfig`) and check the log
   for loop errors.

3. **Therion's layout:**

   ```bash
   therion -l output/therion-layout.log tools/layout.thconfig
   ```

   writes `output/layout-plan.xvi`, `output/layout-extended.xvi` and
   `output/layout.sql`. Rerun it whenever the survey data change.

4. **Check the sketch:**

   ```bash
   python3 -m tools.sketch2therion check Tratmans/Notes/TratmansP.xvi --survey Tratmans
   ```

   Stations Therion doesn't know mean the trip isn't input, the layout
   is stale or `--survey` is wrong. Tratmans fits to 0.3 m, more than
   the few centimetres usual elsewhere, probably because Therion turns
   the survey to the OS grid here.

5. **Convert the plan:**

   ```bash
   python3 -m tools.sketch2therion plan Tratmans/Notes/TratmansP.xvi --survey Tratmans \
     --author 2026.10.20 "Andrew Atkinson" --copyright 2026 "Andrew Atkinson, GPLv3.0+" \
     -o Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion roofs Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion details Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion smooth Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion place Tratmans
   ```

   Scraps are named `XSP1`, `XSP2`, … and cross sections `XPX<station>`.
   `place` inputs the drawing in `X.th` with a `map XMP` of its scraps,
   adds `XMP@X` to `MasterPlan` in `swildonsmaster.th`, and removes
   SexyTopo's own plan `.th2`.

6. **Check:**

   ```bash
   python3 -m tools.sketch2therion review check Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion review gaps Tratmans/TratmansP.th2 TratmansSP1
   python3 -m tools.sketch2therion.th2lint Tratmans/TratmansP.th2
   python3 -m tools.sketch2therion fillcheck --build --projection plan --survey Tratmans
   ```

   `fillcheck --build` builds `swildons-check.thconfig` and lists legs
   outside the fill and splay ends more than 0.5 m outside it.
   `review show` puts the sketch beside the drawing at given stations.
   Go through `Style.md` ("Checking") as well, then finish by hand in
   xTherion (the sketch is linked as a backdrop).

7. **Cross sections on the Swildons sheets.** After a build:

   ```bash
   therion -l output/therion-sections.log tools/sections/sections.thconfig
   python3 -m tools.sections
   ```

   gives the cross section lines arrows the way each section is seen,
   and moves section drawings clear of the passages and each other. A
   new sheet, or a map drawn displaced, needs adding to `SHEETS` in
   `sections/sections.py`.

## Joining up with Stanton's survey

Beyond the resurvey only W. I. Stanton's 1950s–60s survey exists
(`Stanton/`, one folder per trip). The
[plan with Stanton's survey](https://cavesurveying.github.io/uk_mendips_swildons-hole/Swildons-plan-with-stanton.pdf)
shows his stations next to the resurvey's. When a new trip reaches
one of them:

- **Equate the stations** in `Swildons_Centreline.th`, e.g.
  `equate 12@Sump1ToSwildons2 B1@swil2a.wstanton`. Stanton's survey
  beyond that point then hangs off the new data instead of his own
  measurements from the Forty.
- **Flag the replaced legs.** Find the legs of his that the new trip
  replaces, and flag them `duplicate` in his file, as in
  `Stanton/1953-02-08/swildons1-c.th`:

  ```
  flags duplicate
  ...his legs...
  flags not duplicate
  ```

  They are then left out of the length but still join the rest of his
  survey.
- **Check the loop errors** in the build log: a big one means a wrong
  equate.

## PocketTopo

The same commands take PocketTopo files: a `.top`, or the Therion
export `_th.txt`. Two more commands help:

```bash
# a PocketTopo sketch as an XVI backdrop for xTherion
python3 -m tools.sketch2therion xvi Entrance/Trip/pockettopo/Trip.top --view elevation \
  -o Entrance/Trip/pockettopo/Trip_th_e.xvi
# copy PocketTopo's left/right leg directions into the trip's .th
python3 -m tools.sketch2therion extend Entrance/Trip/pockettopo/Trip_th.txt \
  Entrance/Trip/Trip.th
```

PocketTopo's Therion export sometimes lists a side view's stations
somewhere other than where its sketch put them; `check` shows that as
a large distance from stations to walls. The `.top` file is laid out
the way the sketch was drawn, so convert from that instead.

## How it works

The shared tools are described in `sketch2therion/README.md`, and the
rules they follow in `sketch2therion/Style.md`. A change to either is
made in Therion-Sketching.
