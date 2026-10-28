---
name: therion-drawing
description: Conventions for drawing or editing Therion scraps (.th2) in this survey, and the checks to run afterwards. Use when converting sketches, editing walls, water, labels, cross-sections or other symbols, or reviewing a drawing.
---

# Drawing Therion scraps in this survey

The conventions live in one place, `tools/sketch2therion/Style.md`
(the shared Therion-Sketching rules): read it before drawing or editing
a `.th2`, and add to it what the work teaches. Do not copy its rules
here.

- Workflow (SexyTopo to a finished plan, and `review`): `tools/README.md`.
- Cave settings (names, scale, licence): `tools/project.toml`.
- Checks: `python3 -m tools.sketch2therion.th2lint FILE.th2`,
  `python3 -m tools.sketch2therion review check FILE.th2`, and
  `python3 -m tools.sketch2therion fillcheck --build --projection plan`.

## The older drawings

The rest of this file is what was learnt converting Footleg's
PocketTopo sketches (2012 to 2019) with the earlier converter, from a
Therion expert's review of the drawings (Andrew Atkinson). It still
describes those drawings and how to edit them. For new drawings,
`Style.md` wins where the two differ (brown, for example, is the floor
there, not another level). Cross sections on the Swildons sheets are
placed by `python3 -m tools.sections`.


## Walls and the outline

- Every visible line on the outer edge of a scrap has `-outline out`
  set explicitly; no line inside the passage (a step, border or pit
  edge within it) has it.
- Walls are the scrap's outline. Draw each `line wall` with the passage
  on its LEFT, or use `-reverse on` if the passage is on its right
  (Footleg's drawings do; `-reverse on` flips a line).
- Walls enclosing an internal pillar have `-outline in`.
- Do not close the gaps between walls: no invisible walls, and no
  closed invisible fill line with the walls set `-outline none`.
  Therion closes the outline itself, joining each wall's end to the
  nearest free end of another with a straight line
  (`thscrap::get_outline`). Converted sketches can be so broken up that
  this joining goes wrong (it jumps across the passage, or closes the
  outline early); only there does `tidy` keep a gap filled, with the
  wall carried on across a short one or a presumed wall across a longer
  one. `therion_chain` in `tools/sketch2therion/tidy.py` checks it.
- The outline must not cross itself, and no wall may loop back on
  itself. Otherwise Therion warns "invalid scrap outline" (no 3D model
  for the scrap) or MetaPost "scrap outline intersects itself".
- MetaPost also gives that warning for an outline that doesn't cross
  itself, when it miscounts its turns: where one wall ends on the next,
  Therion joins them with a line of no length, which MetaPost takes as
  pointing east, so walls running west across the join can lose a whole
  turn. `mp_turning` in `tools/sketch2therion/smooth.py` counts as
  MetaPost does; turning the walls' ends slightly off due west, or
  making the two walls one line, fixes it.
- A line inside the passage is not a wall: a `line border` (a ledge,
  the edge of another level) or a step (see Symbols: lines). In the
  streamway it's mostly the edge of a step down (a shelf, the stream in
  the low part): `line floor-step`, with the low side on the line's
  LEFT (Therion draws the ticks there). The low side is where the water
  is (flow arrows, pools), not necessarily where the survey line runs.
  One line per step, and steps don't run through the water.

## Symbols: general

- The default clipping normally gives the best result. Most symbols
  are clipped by the outer walls: use that for the best effect.
- `-clip off` only in exceptional circumstances.
- Labels and cross-sections must not overlap passages, including those
  of other surveys on the same sheet.

## Symbols: points

- Slope arrows (`point gradient`): inside the walls, not crossing steps
  or pitch edges, not in water.
- Water flow inside the walls.
- Climbs and pitches are labelled `C2`, `P5`: no units, placed outside
  the passage.
- Draught arrows (`point air-draught -orientation N`) go beside the
  passage, not across it, with a `point x y date -value YYYY.MM.DD`
  for when the draught was seen.

## Symbols: lines

- Draw lines with as few points as follow the shape, smooth in both
  directions (about one a metre, as Footleg's walls are).
- One line per wall, not a run of pieces: Therion caps each line's ends,
  so pieces show as bumps where they meet, and a piece lying along
  another wall draws it twice. Start a new line only where the wall
  changes kind (wall to presumed) or turns a real corner.
  `python3 -m tools.sketch2therion smooth` does both for converted walls.
- Rocks and boulders (`line rock-border`) are closed (`-close on`) and
  not smoothed: straight segments.
- A closed line (`-close on`) ends on its first point. If it doesn't,
  xtherion adds the point itself on loading and is left in a bad state:
  selecting a line then fails ("no such element in array").
- They are drawn in file order and clip each other.
- Large boulders get `line rock-edge` lines inside them to look like 3D
  rocks.
- Boulders at the edge of a passage are best drawn going over the wall
  (the outline clips them).
- Steps by height: significant boundaries and steps under 20 cm are
  `line border`; 20 cm to 2 m and easily climbed, `line floor-step`;
  harder climbs and anything over 2 m, `line pit` (a pitch edge).
- Use `line overhang`, not `ceiling-step`. Both draw their ticks on the
  line's left, so swapping the type keeps the side.

## Symbols: areas

- Water: `line border -subtype invisible -id X -close on` and an `area
  water` naming X. No other border is added to water.
- Water against an outer wall: draw its border outside the wall, so the
  wall is its edge.
- Areas can overlap to show a transition, or pebbles in water.
- Individually drawn rocks can be above or below the water; that needs
  careful ordering and use of clipping.

## Passages over passages

- A passage that drops below another (a rift under the main passage)
  is drawn in its own scrap or alongside: where the upper passage's
  floor edge crosses over it, that edge is a `line overhang` or
  `line floor-step`, not a wall; walls are only the cave's outer edges.
- Noses and fins of rock between passages are drawn: don't let a
  scrap's closing line fill across them.

## Cross-sections

- A `line section` goes right across the passage.
- Its direction arrows don't overlap the passage they mark, and best not
  other passages either.
- `-direction both` by preference; arrows only at the start or end
  (`begin`, `end`) if that's the only option.
- Therion draws the arrows on the line's left, so draw it with the view
  direction (along the survey, from the station towards the next) on
  its left.
- A section drawing must not overlap a passage or another section,
  including those of other surveys on the same sheet.
- `python3 -m tools.sections` does all of this, and
  moves section labels off passages (see `tools/README.md`).

## Fill where nothing was drawn

Use the splay shots, not a guess: in elevation the steep splays give
the roof and floor at each station, in plan the splay ends give the
walls (`python3 -m tools.sketch2therion roofs`, see `tools/README.md`).

## .thconfig layouts

These are set in `gb_layout.thc` and `altitude-colours.th`:

- A sump keeps an opening in its wall about 1 m wide where the dive
  line goes on (the sketch's brown line through the pool).
- Kinks and folds are conversion faults, never cave: a point where a
  line steps back on itself over a short distance, or a wall stub
  under 30 cm turning back off another wall's end. Remove them.
- Water is always blue, so passages never are: the altitude colours
  (`lookup altitude:warm`, used as `color map-fg altitude:warm`) run
  from dark red at the bottom of the cave through orange and yellow to
  green at the entrance.
- Water is solid blue and sump a darker solid blue (hatched only in the
  black-and-white layout).
- Water flow is the same colour as the water.
- The title carries the licence: GPL v3 or later (`map-comment`).
- Labels use 4 text sizes, in descending order (`-scale`):
  - `xl`: area names (Long Dry Way, Short Dry Way, Wet Way, Barnes Loop,
    New Grottoes);
  - `l`: main passages and chambers (Double Pots, Tratman's Temple,
    Sump 1, Water Chamber);
  - `m`: minor passages (Upper Oxbow, Rolling Thunder, the digs);
  - `s`: features (`C2`, Dig, The Well, Folded Strata).

## Checking

Build with the `swildons*.thconfig` files (see `README.md`), then:

- `grep -E "^therion: error|invalid scrap outline" output/*.log`:
  there should be none.
- `grep "intersects itself" output/*.log | sort -u`: only scraps you
  didn't touch.
- Open edited files in xtherion and select a few lines: it should not
  report errors.
- Render and look. poppler (pdftoppm, Evince, Okular) can show white
  holes in Therion's smooth altitude shading that aren't in the PDF;
  check with another renderer (MuPDF) before chasing them.
- In PDFs, overlapping rocks fade rather than clip: a known bug, don't
  try to fix it.

## Reviewing a drawing with someone who knows the cave

The converted drawings follow the sketches closely but misread them in
predictable ways, and only someone who has been there can settle some
of it. What worked, in order:

1. Agree the scope first (plan before elevation: the elevation is a
   bigger job) and work through it a few spots at a time.
2. Find the spots yourself before asking: `review gaps` (straight
   closing lines where the sketch has a wall), merged pools, steps that
   should be walls, lines in brown or green that weren't drawn. Fix
   what the sketch makes certain; ask about the rest.
3. Ask with pictures, never with words alone: `review show` puts the
   original sketch (its colours, legs and station names) beside the
   drawing with station names (`review build` first). One picture per
   question, numbered, 3 to 7 per batch, each naming the stations and
   giving the default you'd take, so the answer can be a word.
4. After fixing, show sketch | before | after (`review show --before`,
   with the old `output/review-plan.pdf` copied aside before editing),
   build every config, and compare the "intersects itself" list with
   the last build: no new warnings.
5. Commit and push each round; main moves (other work), so fetch and
   rebase rather than force.
6. Write each answer down here, as a rule for the next drawing.

`python3 -m tools.sketch2therion review --help` (tools/sketch2therion/
review.py). `review check FILE.th2` gives each scrap's outline as
Therion joins it: valid, and MetaPost's turning number (0 = "intersects
itself").

### How these sketches read (answers from the review)

- The furthest drawn line out from the passage is the wall (the
  surveyor could only have drawn it by seeing it); a line between it
  and the survey is a step or ledge, even when the converter or
  Footleg's tidy-up made the outer one a dashed (presumed) wall.
- Black is wall, including bays and alcoves where the wall bends in and
  out; a black line inside the passage is a step only where it is the
  edge of a shelf. Don't let Therion close a bend with a straight line.
- Brown outlines are other passages at another level or grottoes off
  the passage: each its own scrap, meeting the main passage along one
  shared wall (the same points), not overlapping it.
- Green: in the 2017 sketches, a shelf (draw its edge as a floor step,
  low side to the water); in the 2019 one, arcs across the passage are
  gour pools on flowstone (`line rimstone-dam`), and green "c" marks
  are flowstone.
- A dashed black circle, or orange ticks round a station, is an aven
  (`line chimney`, unclipped where it is wider than the passage); the
  surveyors drew the ticks on the wrong side, so don't copy them.
- Blue hatching: keep separate pools separate and round, as sketched;
  one hatched patch is one pool.
- Thin triangles are slope arrows (`point gradient`, wide end to tip),
  not boulders.
- A pinch between two pools is a real narrowing of the walls.
- A passage dropping under another (a rift below the main passage): its
  edge under the main passage is a floor step, the main passage's edge
  over it an overhang; walls only on the outer edges. Draw the nose of
  rock between passages.
- Water is always blue and nothing else is (the altitude colours avoid
  blue).

### Pitfalls met while fixing

- Walls must meet at exactly the same point; 0.3 units apart makes a
  backwards step that crosses the outline.
- Where two walls meet heading roughly west MetaPost can miscount the
  outline's turns; make them one line (`review check` shows it).
- A curve fitted through a narrow tip can fold over itself; draw tips
  through the sketch's corner points with a sharp corner.
- Before taking `-outline out` off a line, check `join` statements in
  the map files: a scrap joined to another needs that edge.
- New lines must match their neighbours' options (`-outline out`) or
  they won't be merged.
