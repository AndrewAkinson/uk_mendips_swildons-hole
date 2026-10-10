# Tools for continuing the resurvey

How to get a new SexyTopo trip (or an old PocketTopo one) into the
survey, with drawings.

| Path | What it is |
|---|---|
| `sketch2therion/` | Converts SexyTopo and PocketTopo sketches into Therion drawings (`.th2`): plan, extended elevation and cross-sections. |
| `layout.thconfig`, `layout.th` | Exports where Therion puts every station, which the converter fits sketches to. |
| `new-trip-template.th` | A starting point for a new trip's survey file. |
| `requirements.txt` | The one Python library the converter needs (Shapely). |

The converter is how the plan from below the 20 ft Pot to Sump 1, and
all the elevations and cross-sections, were made from Footleg's
PocketTopo sketches. Its output is a faithful first draft, not a
finished drawing. Expect to tidy it in xTherion.

## Setting up

You need Python 3 with Shapely, and Therion (Docker is easiest, as in the
main [README](../README.md#building-it-yourself)):

```bash
pip install -r tools/requirements.txt
therion() { docker run --rm -v "$PWD:/project" \
  -e PROJ_DATA=/project/proj:/usr/share/proj -e PROJ_NETWORK=OFF \
  ghcr.io/paperclipmonkey/therion:6.4.0 "$@"; }
```

Run everything from the top of the repository.

## Underground, in SexyTopo

The converter reads the sketch colours, so draw with these:

| Colour | Becomes |
|---|---|
| Black | Walls. Small closed loops become boulders, and a thin tapering triangle becomes a slope arrow pointing to its narrow end. |
| Brown, grey | Walls of another level or an overlapping passage, such as an oxbow above the streamway in the side view. Where they run inside the passage they become thin borders (ledges, the edge of an upper level). |
| Blue | Water. Hatching or a closed outline becomes a pool, and a squiggle becomes a water-flow arrow. |
| Green | Formations: concentric rings become a stalagmite boss, a small "Y" a stalactite, anything else flowstone. |
| Red, orange, purple | Ignored. Use them for notes, text and leader lines. |

SexyTopo text and symbols are exported as lines in their own colour, so
write notes in red or orange or they will be read as walls.

- **Draw both views:** the plan and the extended elevation. The
  elevation also gives the plan its floor steps, climb heights and
  gradient arrows.
- **Cross-sections:** draw them with SexyTopo's cross-section tool at a
  station. Each becomes a Therion cross-section, cut across the passage
  at that station. In the plan view, it is drawn where you put it.
- **Left and right:** set each leg's extended-elevation direction in
  SexyTopo, as you want the elevation unrolled. SexyTopo exports the
  directions and Therion follows them.
- **Starting from an existing station:** the trip's first station gets
  tied to an existing one afterwards (see below), so its name doesn't
  matter. Note in the book which station it is.

## After the trip

1. **Export.** In SexyTopo use *Export → Therion*. It writes a `.th`
   file, a plan and an extended-elevation `.th2`, and an `.xvi` sketch
   for each. Copy the whole export, plus SexyTopo's own survey files,
   into the trip's own folder, `<area>/<yyyy-mm-dd>/sexytopo/` (for
   example `streamway/2026-11-07/sexytopo/`), so the originals are kept. The
   `.th2` files SexyTopo writes are empty scraps; the converter
   replaces them.

2. **The survey data.** Copy `tools/new-trip-template.th` to
   `Swildons_<Where>.th` in the trip's folder, e.g.
   `streamway/2026-11-07/Swildons_Sump1ToSwildons2.th`:
   - Give it a survey name, e.g. `Sump1ToSwildons2`.
   - Fill in the date, team and copyright.
   - Paste in the `data` and `extend` lines from SexyTopo's `.th`.

   Then tie it in:
   - In `Swildons_Centreline.th`, add
     `input streamway/2026-11-07/Swildons_Sump1ToSwildons2.th` with the
     others, and an equate to the station the trip started from,
     e.g. `equate 0@Sump1ToSwildons2 24.33@TratmansToSump1`.
   - Add `<Survey>@Swildons` to the `ResurveyCentreline` map in
     `swildonsmaster.th`, so the trip's legs appear on the centreline
     sheets.
   - Build (`therion -l output/therion.log swildons.thconfig`) and check the log for loop errors.

3. **Therion's layout.** Export where Therion now puts every station:

   ```bash
   therion -l output/therion-layout.log tools/layout.thconfig
   ```

   This writes `output/layout-plan.xvi` and `output/layout-extended.xvi`.
   Rerun it whenever the survey data or extend flags change.

4. **Check the sketches.**

   ```bash
   python3 -m tools.sketch2therion check streamway/2026-11-07/sexytopo/plan.xvi --survey Sump1ToSwildons2
   python3 -m tools.sketch2therion check streamway/2026-11-07/sexytopo/ee.xvi --survey Sump1ToSwildons2 --elevation
   ```

   It reports:
   - What is in the sketch: stations, legs, splays, cross-sections and
     lines of each colour.
   - Any stations Therion doesn't know: the trip isn't input yet, the
     layout is stale, or `--survey` is wrong.
   - How well the sketch fits Therion's layout. Within a few
     centimetres is normal.
   - Whether some stations need a different shift. In an extended
     elevation that happens where Therion breaks a loop differently
     from the phone, and the sketch is split into one scrap per group
     there. If you'd rather it didn't, change the `extend` flags so
     Therion breaks the loop where you drew it, and re-export the
     layout.
   - How far the stations are from the drawn walls. If that is several
     metres, the drawing doesn't line up with its stations.

5. **Convert.**

   ```bash
   python3 -m tools.sketch2therion plan streamway/2026-11-07/sexytopo/plan.xvi \
     --survey Sump1ToSwildons2 --floor streamway/2026-11-07/sexytopo/ee.xvi \
     --author 2026.11.07 "Michael Waterworth" --copyright 2026 "Michael Waterworth" \
     -o streamway/2026-11-07/Swil1P_Sump1ToSwildons2.th2
   python3 -m tools.sketch2therion extended streamway/2026-11-07/sexytopo/ee.xvi \
     --survey Sump1ToSwildons2 \
     --author 2026.11.07 "Michael Waterworth" --copyright 2026 "Michael Waterworth" \
     -o streamway/2026-11-07/Swil1E_Sump1ToSwildons2.th2
   ```

   Each command prints the scraps it made, and the map they go in.
   The drawing follows Therion's conventions (see `tidy.py`):
   - the walls are the scrap's outline, drawn with the passage on their
     left, so the fill stops at the walls
   - the gaps between walls are left open for Therion to close, except
     where its joining would go wrong (then the wall is carried across a
     short gap, or a presumed wall drawn across a longer one)
   - water has one invisible border, which runs out under the walls it
     lies against so the wall is its edge, and nothing uses `-clip off`
   - big boulders get rock edges, and boulders at the edge of the
     passage go out over the wall; slope arrows are kept off steps,
     pitches and water; climbs are labelled C2 and pitches P5 (no
     units), and labels go outside the passage

   - **Inputs:** un-comment the `input` lines for the two `.th2` files
     in the trip's `.th`. An `input` path is relative to the file it is
     in, so a drawing in the same folder needs only its name.
   - **Plan scraps:** add them to `Streamway1Plan` in
     `streamway/Swildons_MAP_Streamway1.th`, or to a new map listed in
     `MasterPlan`.
   - **Extended scraps:** add them to `StreamwayElevation` in
     `streamway/Swildons_MAP-elev_Streamway.th`.
   - **The `…XS` scrap:** it places the elevation's cross-sections on
     the plan, so it goes in the plan map.

   Options:
   - `--name`: a prefix for the scrap names, if the survey name
     clashes with existing scraps.
   - `--floor-reach` and `--roof-reach`: how far the elevation fill
     looks below and above the legs for the floor and roof (3 m and
     5 m). Raise them for big chambers and pots.
   - `--tol`: how far apart two stations' shifts can be before the
     sketch is split.
   - `--map-scale`: the scale of the sheet it will be printed at
     (default 500; the Entrance Series sheets are 200), for sizing
     labels and arrows.

   For an extended elevation, run this after a build too:

   ```bash
   python3 -m tools.sketch2therion roofs streamway/2026-11-07/Swil1E_Sump1ToSwildons2.th2
   ```

   Where the sketch has no roof or floor, the conversion has to guess.
   This redraws those parts from the splay shots instead: the passage
   goes up to the roof and down to the floor that the steep splays at
   each station measured. Fill well beyond them, from a sketch line
   that belonged to another passage, is cut back. Drawn walls near the
   splay roof or floor still win.

   Plan scraps get the same from the splays (the hull of each leg's
   stations and splay ends): `roofs` on the plan file does both. Then:

   ```bash
   python3 -m tools.sketch2therion details streamway/2026-11-07/Swil1P_Sump1ToSwildons2.th2
   ```

   This turns lines inside the passage into floor steps, with the
   ticks on the low side: towards the water, else the survey's side.
   It drops strokes that just double a wall, and draws gaps in the
   walls along the passage as presumed (dashed) walls. It also redraws
   boulders as clean blocks with facet edges. Check the steps:
   where the ticks aren't on the low side, flip the line in xTherion.

   Last, on both files:

   ```bash
   python3 -m tools.sketch2therion smooth streamway/2026-11-07/Swil1P_Sump1ToSwildons2.th2 \
     streamway/2026-11-07/Swil1E_Sump1ToSwildons2.th2
   ```

   The converted walls come in pieces, a stroke at a time, with four or
   five points a metre. This first makes them one line per wall: pieces
   that double a wall or stick out past it go, walls of the same kind
   that run on from one another (end to start, or within 60 cm and
   heading on) are joined, and so are the walls either side of a short
   presumed wall or a stray spur. Then it refits each wall with as few smooth Bézier
   curves as keep within 10 cm of it, as a wall drawn in xTherion would
   be. Sharp corners stay corners, and each wall keeps its ends, so the
   outline joins up as before. A wall that would then cross itself or
   another, or break the outline for Therion or MetaPost, is fitted more
   tightly or left as it was. In a file that also has hand-drawn scraps,
   name the converted ones with `--scrap`.

   `python3 -m tools.sketch2therion tidy FILE.th2 ...` does the same to
   drawings converted before, and reports how much of each scrap's
   walls ended up on its outline.

6. **Place the cross-sections.** After a build:

   ```bash
   therion -l output/therion-sections.log tools/sketch2therion/sections.thconfig
   python3 -m tools.sketch2therion sections
   ```

   This gives every cross-section line arrows (`-direction both`) that
   point the way the section is seen: along the survey, from its
   station towards the next one. It also carries each line right across
   its passage so the arrows are clear of it (one arrow only where the
   other would land on another passage). And it moves section labels
   off the passages of every survey on the sheet. It also moves any section drawing
   that overlaps a passage or another section, from any survey on the
   same sheet, to the nearest clear spot, preferring one in line with
   the cut. Its label moves with it. A new sheet, or a map drawn
   displaced, needs adding to `SHEETS` in `sections.py`.

7. **Build and tidy.** Build the sheets and look at them. Each `.th2`
   has its sketch linked as a backdrop, so you can open it in xTherion
   and fix what the conversion got wrong. Check especially:
   - **Water-flow and flowstone arrows:** they point the way the
     survey went.
   - **Passage names:** add them as labels.
   - **Ends:** anything cut off where the drawing stops.

## Joining up with Stanton's survey

Beyond the resurvey only W. I. Stanton's 1950s–60s survey exists
(`stanton/`, one folder per trip). The
[plan with Stanton's survey](https://cavesurveying.github.io/uk_mendips_swildons-hole/Swildons-plan-with-stanton.pdf)
shows his stations next to the resurvey's. When a new trip reaches
one of them:

- **Equate the stations** in `Swildons_Centreline.th`, e.g.
  `equate 12@Sump1ToSwildons2 B1@swil2a.wstanton`. Stanton's survey
  beyond that point then hangs off the new data instead of his own
  measurements from the Forty.
- **Flag the replaced legs.** Find the legs of his that the new trip
  replaces, and flag them `duplicate` in his file, as in
  `stanton/1953-02-08/swildons1-c.th`:

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
python3 -m tools.sketch2therion xvi entrance/2016-07-09/pockettopo/Trip.top --view elevation \
  -o entrance/2016-07-09/pockettopo/Trip_th_e.xvi
# copy PocketTopo's left/right leg directions into the trip's .th
python3 -m tools.sketch2therion extend entrance/2016-07-09/pockettopo/Trip_th.txt \
  entrance/2016-07-09/Swildons_Trip.th
```

PocketTopo's Therion export sometimes lists a side view's stations
somewhere other than where its sketch put them; `check` shows that as
a large distance from stations to walls. The `.top` file is laid out
the way the sketch was drawn, so convert from that instead.

## How it works

`sketch2therion/`:

| Module | What it does |
|---|---|
| `xvi.py`, `pockettopo.py` | Read the sketch files into stations, shots and coloured lines, in metres. |
| `register.py` | Fits the sketch to Therion's layout and splits it into groups that fit with one shift each. |
| `walls.py` | Drops strokes drawn twice, joins pieces whose ends meet, smooths, and writes Bézier curves. |
| `symbols.py`, `features.py` | Find boulders, slope arrows, pools, water flow and formations. |
| `floor.py` | Reads the floor off the side view for steps, climbs and gradients. |
| `convert.py` | Builds the scraps: the passage fill and walls-or-borders, then the scraps for the cross-sections and where they go. |
| `sections.py`, `sections.thconfig` | Point the cross-section lines the way each section looks, and move section drawings clear of the passages and each other. |
| `roofs.py` | Fill from the splays where the sketch has no wall: roof and floor in elevation, the passage sides in plan. |
| `details.py` | Floor steps, presumed walls and cleaner boulders in plan. |
| `review.py` | Reviewing a drawing with someone who knows the cave: sketch-beside-drawing pictures, outline gaps the sketch has walls along, outline checks as Therion and MetaPost see them. |
| `smooth.py` | Joins converted walls into one line per wall and refits them with fewer, smooth points, checking the outline still works for Therion and MetaPost. |
| `tidy.py` | Redraws converted scraps the conventional Therion way: walls as the outline (passage on their left), presumed walls where none was sketched, water out to the walls, labels outside the passage. |
