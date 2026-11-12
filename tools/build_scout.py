"""Build a deliberately low-poly 6x6 armoured recon vehicle for MyGame.

Style baseline: Docs/UnitStyle (M1A1 v1, flat-shaded low-poly). The silhouette
is driven by four anchors: six large exposed road wheels, a tall narrow hull
with a sloped glacis, a small remote autocannon turret, and a roof sensor mast.
Flat paint, hard normals, eight-sided wheels, no bolts or photo textures.

    python -I tools/build_scout.py

Requires the same Pillow/NumPy environment as build_ztz99a.py. Reuses that
module's mesh primitives and validated S3O/GLB exporters; it does not rebuild
or overwrite the ZTZ-99A, the M1A1, or the original MBT.glb.
"""

import argparse
import json
import math
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_ztz99a import (Mesh as BaseMesh, Piece, annulus, box, cylinder as round_cylinder,
                          loft, model_bounds, outline, plate, render, vec, walk,
                          write_glb, write_s3o)

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATLAS_SIZE = 256
TRIANGLE_BUDGET = 2400

COLORS = {
    "body": (104, 118, 124), "body_light": (128, 142, 147),
    "body_dark": (76, 88, 94), "body_edge": (92, 104, 110),
    "rubber": (28, 31, 32), "hub": (122, 130, 130),
    "black": (16, 20, 22), "glass": (58, 118, 128),
    "glass_dark": (26, 54, 60), "steel": (100, 106, 102),
    "lamp": (232, 224, 176), "red": (150, 52, 44),
    "team": (68, 133, 185), "canvas": (120, 116, 96),
}
RECTS = {name: (2+(i % 4)*32, 2+(i//4)*32, 29+(i % 4)*32, 29+(i//4)*32)
         for i, name in enumerate(COLORS)}
RECTS.update(mark=(132, 4, 252, 124), grille=(4, 132, 124, 252))

WHEEL_RADIUS = 5.4
WHEEL_HALF_WIDTH = 2.3
WHEEL_X = 13.9
WHEEL_Y = WHEEL_RADIUS
WHEEL_Z = (16.5, 0.0, -16.5)
HULL_LAYERS = (
    (6.0, outline(10.2, -23.0, 21.0, 2.0)),
    (10.8, outline(11.8, -25.5, 24.5, 2.4)),
    (17.2, outline(11.4, -24.5, 19.5, 2.0)),
    (20.6, outline(9.7, -23.0, 11.5, 1.6)),
)
TURRET_LAYERS = (
    (0.9, outline(7.6, -7.6, 6.8, 1.2)),
    (3.2, outline(6.9, -7.0, 5.8, 1.0)),
    (5.2, outline(5.7, -5.8, 3.9, 0.8)),
)
GLACIS_BOTTOM = (9.4, 17.2, 19.5)   # outline() front edge is width-bevel, not width
GLACIS_TOP = (8.1, 20.6, 11.5)


class Mesh(BaseMesh):
    """Flat semantic colour swatches; one UV per face, never a stretched texture."""

    def face(self, points, material="body", outward=None, normals=None, uvs=None):
        if uvs is None:
            x0, y0, x1, y1 = RECTS[material]
            uv = ((x0+x1)/(2*ATLAS_SIZE), 1-(y0+y1)/(2*ATLAS_SIZE))
            uvs = [uv]*len(points)
        super().face(points, material, outward, normals, uvs)


def cylinder(mesh, start, end, radius, material="body", segments=8,
             end_radius=None, caps=True):
    round_cylinder(mesh, start, end, radius, material, segments=segments,
                   end_radius=end_radius, caps=caps, smooth=False)


def decal(mesh, points, material, outward):
    x0, y0, x1, y1 = RECTS[material]
    uvs = [(x0/ATLAS_SIZE, 1-y1/ATLAS_SIZE), (x1/ATLAS_SIZE, 1-y1/ATLAS_SIZE),
           (x1/ATLAS_SIZE, 1-y0/ATLAS_SIZE), (x0/ATLAS_SIZE, 1-y0/ATLAS_SIZE)]
    mesh.face(points, material, outward=outward, uvs=uvs)


def make_atlas():
    diffuse = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), COLORS["body"]+(0,))
    material = Image.new("RGBA", diffuse.size, (0, 12, 0, 255))
    paint, surface = ImageDraw.Draw(diffuse), ImageDraw.Draw(material)
    for name, color in COLORS.items():
        x0, y0, x1, y1 = RECTS[name]
        rect = (x0-2, y0-2, x1+2, y1+2)
        paint.rectangle(rect, fill=color+(255 if name == "team" else 0,))
        reflection = 35 if name in ("glass", "steel") else 20 if name == "glass_dark" \
            else 6 if name == "rubber" else 12
        surface.rectangle(rect, fill=(0, reflection, 0, 255))

    # One large stencil mark: a solid recon triangle over a single bar.
    x0, y0, x1, y1 = RECTS["mark"]
    paint.rectangle((x0, y0, x1, y1), fill=COLORS["body_dark"]+(0,))
    cx = (x0+x1)/2
    paint.polygon([(cx, y0+16), (x1-16, y1-26), (x0+16, y1-26)],
                  fill=COLORS["lamp"]+(0,))
    paint.rectangle((x0+24, y1-18, x1-24, y1-10), fill=COLORS["lamp"]+(0,))

    # Rear deck vent: wide painted slots instead of dozens of modelled louvers.
    x0, y0, x1, y1 = RECTS["grille"]
    paint.rectangle((x0, y0, x1, y1), fill=COLORS["body_dark"]+(0,))
    for y in (y0+14, y0+38, y0+62, y0+86):
        paint.rectangle((x0+10, y, x1-10, y+12), fill=COLORS["black"]+(0,))
    return diffuse, material


def wheel_mesh(name, radius):
    mesh = Mesh(name)
    cylinder(mesh, (-WHEEL_HALF_WIDTH, 0, 0), (WHEEL_HALF_WIDTH, 0, 0), radius, "rubber", 8)
    for side in (-1, 1):
        x = side*(WHEEL_HALF_WIDTH+0.02)
        points = [(x, radius*0.74*math.cos(i*math.tau/8),
                   radius*0.74*math.sin(i*math.tau/8)) for i in range(8)]
        mesh.face(points, "hub", outward=(side, 0, 0))
        hub = [(side*(WHEEL_HALF_WIDTH+0.05), radius*0.26*math.cos(i*math.tau/6),
                radius*0.26*math.sin(i*math.tau/6)) for i in range(6)]
        mesh.face(hub, "body_dark", outward=(side, 0, 0))
    return mesh


def glacis_point(u, v):
    """u in [-1,1] across the nose, v in [0,1] from the lower edge to the roof."""
    bottom = vec((GLACIS_BOTTOM[0]*u, GLACIS_BOTTOM[1], GLACIS_BOTTOM[2]))
    top = vec((GLACIS_TOP[0]*u, GLACIS_TOP[1], GLACIS_TOP[2]))
    return bottom + (top-bottom)*v


def glacis_quad(u0, u1, v0, v1, lift=0.06):
    normal = vec((0, 0.92, 0.39))
    return [glacis_point(u0, v0)+normal*lift, glacis_point(u1, v0)+normal*lift,
            glacis_point(u1, v1)+normal*lift, glacis_point(u0, v1)+normal*lift]


def make_hull():
    mesh = Mesh("scout_hull")
    loft(mesh, HULL_LAYERS, "body")
    for side in (-1, 1):
        # A continuous fender over all three wheels, with flexible mud flaps.
        # The fender is deliberately narrower than the tyre so the six-wheel
        # rhythm still reads from the RTS top-down camera.
        box(mesh, (side*12.7, 11.15, 0.0), (3.2, 0.9, 46.0), "body_light")
        for z in (-22.3, 22.3):
            box(mesh, (side*12.7, 9.3, z), (3.2, 3.2, 0.6), "rubber")
        # Team colour reads from the RTS top-down camera, not only from the side.
        box(mesh, (side*12.7, 11.66, 7.0), (2.6, 0.22, 6.0), "team")
        # Stowage boxes sit inside the fender line so the wheels stay readable.
        for z in (-13.0, 0.5):
            box(mesh, (side*12.05, 13.6, z), (1.5, 4.4, 7.4), "body_edge")
            box(mesh, (side*12.85, 13.6, z), (0.18, 3.4, 6.2), "body_dark")
        # Headlight housings sit on the lower glacis, guarded by a thin rail.
        cylinder(mesh, (side*7.4, 15.4, 20.3), (side*7.4, 15.4, 21.6), 1.25, "body_dark")
        cylinder(mesh, (side*7.4, 15.4, 21.6), (side*7.4, 15.4, 21.85), 0.95, "lamp")
        # Exhaust and rear light cluster.
        cylinder(mesh, (side*9.6, 8.4, -24.9), (side*9.6, 8.4, -26.6), 0.72, "steel")
        box(mesh, (side*9.4, 14.6, -24.75), (2.6, 1.4, 0.3), "red")

    # Nose: bumper, winch and a plate that follows the real slope of the glacis.
    box(mesh, (0, 8.1, 25.2), (20.8, 3.0, 1.5), "body_dark")
    box(mesh, (0, 9.9, 25.4), (6.0, 1.2, 1.2), "body_dark")
    for x in (-6.0, 6.0):
        box(mesh, (x, 8.1, 26.1), (2.2, 1.6, 0.5), "steel")
        box(mesh, (x, 8.1, 23.6), (1.6, 1.4, 4.2), "body_dark")
    cylinder(mesh, (-4.2, 10.4, 25.6), (4.2, 10.4, 25.6), 1.15, "steel", 10)
    plate(mesh, glacis_quad(-0.86, 0.86, 0.06, 0.94, 0.10), 0.34, "body_light",
          normal=(0, 0.92, 0.39))
    for u in (-0.42, 0.0, 0.42):
        mesh.face(glacis_quad(u-0.10, u+0.10, 0.64, 0.80, 0.13), "glass", outward=(0, 0.92, 0.39))
    mesh.face(glacis_quad(-0.72, -0.58, 0.30, 0.44, 0.13), "glass_dark", outward=(0, 0.92, 0.39))
    mesh.face(glacis_quad(0.58, 0.72, 0.30, 0.44, 0.13), "glass_dark", outward=(0, 0.92, 0.39))

    # Roof: driver hatch, lifting eyes and the rear engine deck vent.
    cylinder(mesh, (0, 20.55, 2.0), (0, 21.35, 2.0), 2.7, "body_dark", 12)
    cylinder(mesh, (0, 21.35, 2.0), (0, 21.75, 2.0), 2.35, "body_light", 12)
    for x, z in ((-7.4, -18.5), (7.4, -18.5)):
        box(mesh, (x, 20.9, z), (1.8, 0.6, 1.0), "body_edge")
    box(mesh, (0, 20.62, -17.2), (16.0, 0.24, 9.6), "body_dark")
    decal(mesh, [(-7.2, 20.76, -13.0), (7.2, 20.76, -13.0),
                 (7.2, 20.76, -21.4), (-7.2, 20.76, -21.4)], "grille", (0, 1, 0))

    # Rear door with hinges, handle and a stencil mark.
    plate(mesh, [(-5.2, 8.4, -24.9), (5.2, 8.4, -24.9),
                 (5.2, 18.2, -24.9), (-5.2, 18.2, -24.9)], 0.45, "body_light",
          normal=(0, 0, -1))
    for y in (10.2, 13.2, 16.2):
        box(mesh, (5.9, y, -25.45), (0.9, 1.0, 0.35), "body_dark")
    box(mesh, (-4.4, 13.2, -25.5), (0.5, 1.6, 0.3), "steel")
    decal(mesh, [(3.2, 9.2, -25.38), (-3.2, 9.2, -25.38),
                 (-3.2, 15.2, -25.38), (3.2, 15.2, -25.38)], "mark", (0, 0, -1))

    # Two jerry cans flank the door. No spare wheel: a seventh wheel would blur
    # the six-wheel rhythm that identifies this unit from the RTS camera.
    for side in (-1, 1):
        box(mesh, (side*7.9, 16.0, -25.3), (2.8, 3.8, 1.6), "canvas")
        box(mesh, (side*7.9, 17.95, -25.3), (1.0, 0.3, 0.6), "body_dark")

    # Two thin antennas; no segmented decorative hardware.
    for side in (-1, 1):
        cylinder(mesh, (side*8.2, 20.5, -20.0), (side*8.2, 30.2, -21.2), 0.16,
                 "steel", 4, end_radius=0.07)
    return mesh


def make_turret():
    mesh = Mesh("scout_turret")
    cylinder(mesh, (0, -0.45, 0), (0, 0.95, 0), 6.3, "body_dark", 12)
    loft(mesh, TURRET_LAYERS, "body")
    # Sloped front plate and a compact sight; the turret stays a small volume.
    plate(mesh, [(-4.2, 1.2, 6.9), (4.2, 1.2, 6.9), (3.4, 4.6, 4.2), (-3.4, 4.6, 4.2)],
          0.28, "body_light", normal=(0, 0.62, 0.78))
    box(mesh, (2.6, 5.9, 1.2), (2.6, 2.2, 3.2), "body_dark")
    mesh.face([(1.4, 5.3, 2.82), (3.8, 5.3, 2.82), (3.8, 6.6, 2.82), (1.4, 6.6, 2.82)],
              "glass", outward=(0, 0, 1))
    cylinder(mesh, (-2.6, 5.2, -0.6), (-2.6, 5.95, -0.6), 1.9, "body_edge", 10)
    cylinder(mesh, (-2.6, 5.95, -0.6), (-2.6, 6.15, -0.6), 1.6, "body_light", 10)
    # Team plates sit on the vertical rear face, not on a slope.
    for side in (-1, 1):
        box(mesh, (side*3.4, 2.6, -7.35), (3.2, 2.2, 0.3), "team")
        # Three smoke dischargers per side, inclined forward and outward.
        for i in range(3):
            start = vec((side*5.6, 4.2, -1.2+i*1.5))
            axis = vec((side*0.55, 0.55, 0.63))
            axis = axis/np.linalg.norm(axis)
            cylinder(mesh, start, start+axis*2.2, 0.42, "steel", 6)
            annulus(mesh, start+axis*2.25, axis, 0.44, 0.28, "black", 6)
    # Sensor mast: a thin pole and one box head, the recon signature.
    cylinder(mesh, (0, 5.1, -4.9), (0, 10.6, -4.9), 0.36, "steel", 6, end_radius=0.28)
    box(mesh, (0, 11.5, -4.9), (2.2, 1.8, 1.5), "body_dark")
    mesh.face([(-0.8, 11.0, -4.14), (0.8, 11.0, -4.14),
               (0.8, 12.0, -4.14), (-0.8, 12.0, -4.14)], "glass", outward=(0, 0, 1))
    box(mesh, (0, 10.2, -4.9), (1.2, 0.5, 1.0), "body_edge")
    # Ammunition box and a short antenna on the roof.
    box(mesh, (-5.4, 3.0, 0.4), (2.2, 2.8, 4.2), "canvas")
    cylinder(mesh, (4.9, 5.2, -3.4), (4.9, 10.4, -4.2), 0.12, "steel", 4, end_radius=0.05)
    return mesh


def make_gun():
    mesh = Mesh("scout_gun")
    box(mesh, (0, 0, 0.4), (5.4, 3.4, 3.2), "body_dark")
    cylinder(mesh, (0, 0, 1.9), (0, 0, 16.0), 0.82, "body_light", 8)
    cylinder(mesh, (0, 0, 16.0), (0, 0, 18.0), 1.12, "body_dark", 8)
    annulus(mesh, (0, 0, 18.02), (0, 0, 1), 1.12, 0.62, "black", 8)
    cylinder(mesh, (0, 0, 18.0), (0, 0, 18.06), 0.60, "black", 8)
    cylinder(mesh, (-1.9, 0.3, 1.9), (-1.9, 0.3, 9.2), 0.30, "black", 6)
    box(mesh, (2.4, 0.2, 3.4), (1.2, 1.8, 3.0), "body_edge")
    return mesh


def make_model():
    gun = Piece("Gun", (0, 3.2, 6.0), make_gun(), [Piece("Flare", (0, 0, 18.2))])
    turret = Piece("Turret", (0, 20.6, -3.0), make_turret(), [gun])
    root = Piece("Base", (0, 0, 0), make_hull(), [turret])
    wheel = wheel_mesh("scout_wheel", WHEEL_RADIUS)
    for side, label in ((-1, "L"), (1, "R")):
        for i, z in enumerate(WHEEL_Z, 1):
            root.children.append(Piece(f"Wheel{label}{i}", (side*WHEEL_X, WHEEL_Y, z), wheel))
    return root

def write_rig_data(path):
    path.write_text(
        "-- Generated by tools/build_scout.py; do not edit.\n"
        "-- X right, Y up, Z forward. Wheel spin is driven by real displacement.\n"
        "return {\n"
        f"    radius = {WHEEL_RADIUS:.17g},\n"
        f"    halfWidth = {WHEEL_X:.17g},\n"
        "    wheelCount = 3,\n"
        f"    wheelZ = {{{', '.join(f'{z:.17g}' for z in WHEEL_Z)}}},\n"
        "    left = { \"WheelL1\", \"WheelL2\", \"WheelL3\" },\n"
        "    right = { \"WheelR1\", \"WheelR2\", \"WheelR3\" },\n"
        "}\n", encoding="utf-8")


def make_previews(model, diffuse, material, directory):
    render(model, diffuse, material, directory/"scout_front.png",
           eye=(78, 58, 96), target=(0, 13, 2))
    render(model, diffuse, material, directory/"scout_rear.png",
           eye=(-82, 54, -92), target=(0, 13, -2))
    side = render(model, diffuse, material, directory/"scout_side.png",
                  eye=(112, 15, 0), target=(0, 14, 0), width=1400, height=640)
    front = render(model, diffuse, material, directory/"scout_front_ortho.png",
                   eye=(0, 15, 110), target=(0, 14, 0), width=680, height=640)
    top = render(model, diffuse, material, directory/"scout_top.png",
                 eye=(0, 120, 0), target=(0, 0, 0), width=680, height=1000)
    sheet = Image.new("RGB", (1500, 1560), (226, 230, 221))
    sheet.paste(side.convert("RGB"), (50, 80))
    sheet.paste(front.convert("RGB"), (55, 840))
    sheet.paste(top.resize((612, 900), Image.Resampling.LANCZOS).convert("RGB"), (815, 660))
    font = ImageFont.load_default(size=27)
    draw = ImageDraw.Draw(sheet)
    for text, xy in (("FV-6 SCOUT / LOW-POLY", (55, 30)), ("SIDE", (55, 100)),
                     ("FRONT", (55, 825)), ("TOP", (815, 670))):
        draw.text(xy, text, fill=(58, 63, 55), font=font)
    sheet.save(directory/"scout_views.png")
    icon = render(model, diffuse, material, directory/"scout_icon_source.png",
                  eye=(86, 66, 104), target=(0, 13, 1), width=512, height=512, transparent=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT/"UnitPics"/"scout.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-preview", action="store_true")
    args = parser.parse_args()
    model = make_model()
    diffuse, material = make_atlas()
    count = sum(len(p.mesh.indices)//3 for p, _ in walk(model) if p.mesh)
    assert count <= TRIANGLE_BUDGET, f"Low-poly budget exceeded: {count} > {TRIANGLE_BUDGET}"
    objects, textures, previews = ROOT/"Objects3d", ROOT/"UnitTextures", ROOT/"tools"/"previews"
    for folder in (objects, textures, previews, ROOT/"Scripts", ROOT/"UnitPics"):
        folder.mkdir(parents=True, exist_ok=True)
    diffuse.save(textures/"scout_diffuse.tga", compression=None)
    material.save(textures/"scout_material.tga", compression=None)
    write_s3o(model, objects/"scout.s3o", textures=("scout_diffuse.tga", "scout_material.tga"))
    write_glb(model, diffuse, material, objects/"scout.glb", generator="MyGame low-poly FV-6 Scout")
    write_rig_data(ROOT/"Scripts"/"scout_rig_data.lua")
    low, high = model_bounds(model)
    manifest = dict(name="FV-6 Scout", style="flat-shaded low-poly",
                    triangle_budget=TRIANGLE_BUDGET, triangles=count,
                    pieces=[p.name for p, _ in walk(model)],
                    bounds=dict(min=low.tolist(), max=high.tolist()),
                    texture_size=list(diffuse.size), coordinates="X right, Y up, Z forward",
                    native_model="Objects3d/scout.s3o", exchange_model="Objects3d/scout.glb",
                    rig_data="Scripts/scout_rig_data.lua",
                    wheel=dict(radius=WHEEL_RADIUS, halfWidth=WHEEL_X,
                               z=list(WHEEL_Z), count=3))
    (previews/"scout_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(f"Built FV-6 Scout: {count} triangles / {len(manifest['pieces'])} pieces", flush=True)
    if not args.no_preview:
        make_previews(model, diffuse, material, previews)
        print("Rendered front, rear, orthographic views and build icon", flush=True)


if __name__ == "__main__":
    main()
