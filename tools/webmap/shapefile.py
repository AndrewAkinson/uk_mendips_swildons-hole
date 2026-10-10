"""Just enough of the ESRI shapefile format to read Therion's export.

Therion's `export map -fmt esri` and `export model -fmt esri` write a
directory of shapefiles: points, polylines and polygons (some with Z),
each with a .dbf of attributes. This reads them into plain Python, so the
build needs no GDAL or pyshp.
"""
import struct


def read_dbf(path):
    """The attribute table, as a list of {field: str}."""
    b = open(path, 'rb').read()
    n, header, size = struct.unpack('<4xIHH', b[:12])
    fields, o = [], 32
    while b[o] != 0x0d:
        fields.append((b[o:o + 11].split(b'\0')[0].decode('ascii'), b[o + 16]))
        o += 32
    rows = []
    for i in range(n):
        r, p, row = b[header + i * size:header + (i + 1) * size], 1, {}
        for name, length in fields:
            row[name] = r[p:p + length].decode('utf-8', 'replace').strip()
            p += length
        rows.append(row)
    return rows


def read_shp(path):
    """One entry per record: None, an (x, y[, z]) point, or a list of
    parts, each a list of (x, y[, z]) points."""
    b = open(path, 'rb').read()
    o, out = 100, []
    while o < len(b):
        size = struct.unpack('>i', b[o + 4:o + 8])[0] * 2
        rec, o = b[o + 8:o + 8 + size], o + 8 + size
        kind = struct.unpack('<i', rec[:4])[0]
        if kind == 0:
            out.append(None)
        elif kind in (1, 11, 21):
            x, y = struct.unpack('<2d', rec[4:20])
            out.append((x, y, struct.unpack('<d', rec[20:28])[0]) if kind == 11 else (x, y))
        elif kind in (3, 5, 13, 15, 23, 25):
            nparts, npoints = struct.unpack('<2i', rec[36:44])
            starts = list(struct.unpack(f'<{nparts}i', rec[44:44 + 4 * nparts])) + [npoints]
            p0 = 44 + 4 * nparts
            xy = struct.unpack(f'<{2 * npoints}d', rec[p0:p0 + 16 * npoints])
            if kind in (13, 15):
                z0 = p0 + 16 * npoints + 16
                z = struct.unpack(f'<{npoints}d', rec[z0:z0 + 8 * npoints])
                pts = [(xy[2 * i], xy[2 * i + 1], z[i]) for i in range(npoints)]
            else:
                pts = [(xy[2 * i], xy[2 * i + 1]) for i in range(npoints)]
            out.append([pts[starts[i]:starts[i + 1]] for i in range(nparts)])
        else:
            raise ValueError(f'{path}: shape type {kind} not handled')
    return out


def read(stem):
    """[(attributes, geometry)] for stem.shp and stem.dbf."""
    return list(zip(read_dbf(stem + '.dbf'), read_shp(stem + '.shp')))
