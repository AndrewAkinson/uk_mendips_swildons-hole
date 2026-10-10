# The map and the GeoJSON

The survey on a 2D web map, over the ground, and as GeoJSON to download.

```bash
python3 -m tools.webmap      # after the main build and tools.model3d
python3 -m tools.webmap --standalone preview.html    # also a single file to open from disk
```

## What it writes

| File | What's in it |
|---|---|
| `output/Swildons-map.geojson` | The plan drawing. Passage outlines as polygons (`kind: passage`, one per scrap, with its altitude, depth below the entrance and the rock above it), `area`s (water, clay, pebbles, ...), `line`s (walls, borders, floor steps, pits, ...) and `point`s (labels, water flow, gradients, formations). Lines, areas and points carry the altitude of their scrap; arrows have a compass `bearing`. |
| `output/Swildons-centreline.geojson` | Every `leg` (3D lines, with `source` resurvey or stanton, and `splay`, `duplicate`, `surface` flags) and `station` (3D points named `name@survey`, with altitude, depth below the entrance, and the LIDAR ground and rock above where there is LIDAR). |
| `output/map/` | The page: `index.html` (MapLibre GL JS), `map.json`, `hillshade.png` and `contours.geojson` (1 m contours). |

Coordinates are WGS84 longitude and latitude (RFC 7946), altitudes in
metres above OS datum.

## How

`swildons.thconfig` exports the plan and the model as shapefiles
(`-fmt esri`) into `output/esri-plan/` and `output/esri-model/`. They
are in OS grid metres within square ST, and this turns them into
lat/long the way `tools/model3d` does: the OS formulae with a Helmert
shift, moved so the entrance lands where Therion puts it with OSTN15.
The result agrees with Therion's own KML to within 3 cm across the cave.

Two things Therion does when it draws the map but not in the
shapefiles are done here: area fills and detail lines are clipped to
their scrap's outline (this needs Shapely; without it they are left
whole, poking past the walls in places), and station names come from
the SQL export, since the shapefile stores `13.50` as a number.

The ground is the LIDAR that `tools/model3d` saved in `output/3d/`
(2 m cells): the hillshade, the contours, and the rock above each
station and passage come from it. Without it the map has no ground.

## The page

Backgrounds are OpenStreetMap data drawn with OpenFreeMap's Liberty
style (vector tiles, free and keyless; the tiles from
tile.openstreetmap.org are refused to a page opened from disk) or Esri
imagery. The passages are coloured by altitude with the colours of
`altitude-colours.th`, higher ones drawn over lower ones; clicking
lists every level under the point. Stanton's survey beyond the resurvey
has no drawing yet, so it is shown as a broad centreline, also coloured
by altitude.

The page loads the GeoJSON from the site, so it has to be served over
the web. `--standalone` writes a copy with everything inside it, to open
straight from disk.
