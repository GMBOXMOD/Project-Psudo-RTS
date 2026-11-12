"""Build a deliberately low-poly six-legged spider mech for MyGame.

Style baseline: Docs/UnitStyle (M1A1 v1, flat-shaded low-poly). Anchors: eight
splayed segmented legs with knees above the hull, a low wide chassis, a small
turret, and amber sensor lenses. Legs are rigid two-segment pieces driven by a
distance-based gait, not a baked animation.

    python -I tools/build_spider.py

Reuses build_ztz99a.py's primitives and S3O/GLB exporters; does not touch any
existing unit or the scout.
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
TRIANGLE_BUDGET = 3200

COLORS = {
    "body": (76, 82, 88), "body_light": (102, 110, 116),
    "body_dark": (48, 52, 58), "body_edge": (88, 94, 100),
    "rubber": (26, 28, 30), "hub": (110, 116, 120),
    "black": (14, 16, 18), "glass": (196, 118, 46),
    "glass_dark": (120, 62, 24), "steel": (122, 126, 122),
    "lamp": (236, 196, 120), "red": (156, 48, 40),
    "team": (68, 133, 185), "canvas": (96, 92, 78),
}
RECTS = {name: (2+(i % 4)*32, 2+(i//4)*32, 29+(i % 4)*32, 29+(i//4)*32)
         for i, name in enumerate(COLORS)}
RECTS.update(mark=(132, 4, 252, 124), grille=(4, 132, 124, 252))

HIP_X = 8.5
HIP_Y = 13.0
HIP_Z = (-8.0, 0.0, 8.0)
SPLAY = (26.0, 0.0, -26.0)      # degrees, front to rear on the right side
LEG_YAW = {}
KNEE = (9.0, 9.0)                        # knee offset in the hip plane
FOOT = (11.0, -22.0)                     # foot offset in knee-local space
STRIDE = 18.0
STANCE_FRACTION = 0.6
HIP_AMPLITUDE = math.radians(34)
KNEE_LIFT = math.radians(15)


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

    # One stencil: a filled hexagon (the chassis plan) over a single bar.
    x0, y0, x1, y1 = RECTS["mark"]
    paint.rectangle((x0, y0, x1, y1), fill=COLORS["body_dark"]+(0,))
    cx, cy, r = (x0+x1)/2, (y0+y1)/2 - 6, 38
    hexagon = [(cx + r*math.cos(math.pi/6 + i*math.pi/3),
                cy + r*math.sin(math.pi/6 + i*math.pi/3)) for i in range(6)]
    paint.polygon(hexagon, fill=COLORS["lamp"]+(0,))
    paint.rectangle((x0+26, y1-20, x1-26, y1-12), fill=COLORS["lamp"]+(0,))

    # Vent grille: wide painted slots, not modelled louvers.
    x0, y0, x1, y1 = RECTS["grille"]
    paint.rectangle((x0, y0, x1, y1), fill=COLORS["body_dark"]+(0,))
    for y in (y0+14, y0+38, y0+62, y0+86):
        paint.rectangle((x0+10, y, x1-10, y+12), fill=COLORS["black"]+(0,))
    return diffuse, material


def rot_y(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.asarray(((c, 0, s), (0, 1, 0), (-s, 0, c)))


def rotate_mesh(mesh, degrees, name):
    out = Mesh(name)
    matrix = rot_y(degrees).T
    out.positions = (np.asarray(mesh.positions) @ matrix).tolist()
    out.normals = (np.asarray(mesh.normals) @ matrix).tolist()
    out.uvs = list(mesh.uvs)
    out.indices = list(mesh.indices)
    return out


def posed_for_preview(model):
    """Bake each leg's resting hip yaw into a copy used only for previews/bounds.

    The exported S3O keeps the canonical leg; the engine applies the yaw at
    runtime. Previews must still show the rest pose the player will see.
    """
    import copy
    root = copy.deepcopy(model)

    def pose(piece, matrix, yaw):
        if piece.mesh:
            piece.mesh = rotate_mesh(piece.mesh, yaw, piece.name + "_pose")
        for child in piece.children:
            child.offset = tuple(matrix @ np.asarray(child.offset))
            pose(child, matrix, yaw)

    for piece, _ in walk(root):
        yaw = LEG_YAW.get(piece.name)
        if yaw is None:
            continue
        pose(piece, rot_y(yaw), yaw)
    return root


def femur_mesh():
    """Hip-local: joint at the origin, femur rising to the knee at (7, 7)."""
    mesh = Mesh("spider_femur")
    cylinder(mesh, (-1.9, 0, 0), (1.9, 0, 0), 2.1, "body_dark", 6)
    for x in (-1.9, 1.9):
        annulus(mesh, (x, 0, 0), (1 if x > 0 else -1, 0, 0), 2.15, 1.35, "steel", 6)
    cylinder(mesh, (1.4, 0, 0), (KNEE[0], KNEE[1], 0), 2.0, "body", 6, end_radius=1.7)
    # A single armour plate along the top of the femur, no bolts.
    plate(mesh, [(-0.4, 1.9, -1.1), (6.6, 7.0, -1.1), (6.6, 7.0, 1.1), (-0.4, 1.9, 1.1)],
          0.45, "body_edge", normal=(0.45, 0.89, 0))
    return mesh


def tibia_mesh():
    """Knee-local: joint at the origin, foot at (8, -20)."""
    mesh = Mesh("spider_tibia")
    cylinder(mesh, (0, 0, -2.0), (0, 0, 2.0), 1.8, "body_dark", 6)
    for z in (-2.0, 2.0):
        annulus(mesh, (0, 0, z), (0, 0, 1 if z > 0 else -1), 1.85, 1.1, "steel", 6)
    cylinder(mesh, (0, 0, 0), (10.4, -20.8, 0), 1.5, "body", 6, end_radius=0.72)
    # Foot pad and claw; the pad bottom sits exactly on y=0 in world space.
    box(mesh, (10.9, -21.5, 0), (2.4, 1.0, 2.6), "black")
    cylinder(mesh, (10.9, -21.0, 0), (11.3, -19.6, 0), 0.5, "steel", 5)
    return mesh


def make_legs():
    """One canonical leg, shared by all six; the splay is a runtime hip yaw."""
    femur, tibia = femur_mesh(), tibia_mesh()
    pieces = []
    for side, label in ((-1, "L"), (1, "R")):
        for index, (z, angle) in enumerate(zip(HIP_Z, SPLAY), 1):
            LEG_YAW[f"Hip{label}{index}"] = (180.0 - angle) if side < 0 else angle
            knee = Piece(f"Knee{label}{index}", (KNEE[0], KNEE[1], 0), tibia)
            pieces.append(Piece(f"Hip{label}{index}",
                                (side * HIP_X, HIP_Y, z), femur, [knee]))
    return pieces


def make_hull():
    mesh = Mesh("spider_hull")
    loft(mesh, [
        (8.0, outline(8.8, -11.5, 10.5, 1.8)),
        (11.5, outline(10.4, -13.0, 12.5, 2.2)),
        (16.5, outline(9.6, -12.0, 10.0, 2.0)),
        (19.6, outline(6.8, -9.0, 6.0, 1.4)),
    ], "body")
    # Wide belly plate keeps the hull from looking like a floating box.
    plate(mesh, [(-7.6, 8.05, -11.0), (7.6, 8.05, -11.0),
                 (7.6, 8.05, 10.0), (-7.6, 8.05, 10.0)], 0.5, "body_dark", normal=(0, -1, 0))
    # Front sensor head with three amber lenses.
    box(mesh, (0, 14.6, 12.4), (9.4, 5.4, 3.6), "body_dark")
    for x in (-2.9, 0.0, 2.9):
        cylinder(mesh, (x, 14.6, 14.2), (x, 14.6, 14.9), 1.15, "body_edge", 6)
        cylinder(mesh, (x, 14.6, 14.9), (x, 14.6, 15.05), 0.85, "glass", 6)
    box(mesh, (0, 17.6, 12.0), (6.2, 1.2, 2.6), "body_light")
    # Side armour cheeks and team panels.
    for side in (-1, 1):
        plate(mesh, [(side*10.4, 11.6, -8.0), (side*10.4, 11.6, 6.0),
                     (side*9.4, 16.2, 5.0), (side*9.4, 16.2, -7.0)],
              0.45, "body_edge", normal=(side, 0, 0))
        box(mesh, (side*10.55, 13.4, 8.6), (0.4, 2.4, 4.2), "team")
        box(mesh, (side*9.9, 11.2, -10.4), (2.2, 1.6, 2.2), "steel")
    # Rear deck vent and two small exhausts.
    box(mesh, (0, 19.62, -7.4), (9.6, 0.24, 6.4), "body_dark")
    for side in (-1, 1):
        # Horizontal team strips stay readable from the RTS top-down camera.
        box(mesh, (side*5.7, 19.66, -7.4), (1.6, 0.14, 5.6), "team")
    decal(mesh, [(-4.2, 19.76, -4.6), (4.2, 19.76, -4.6),
                 (4.2, 19.76, -10.2), (-4.2, 19.76, -10.2)], "grille", (0, 1, 0))
    for x in (-4.6, 4.6):
        cylinder(mesh, (x, 18.6, -12.4), (x, 18.6, -14.6), 0.9, "steel", 6)
    # One stencil on the rear plate.
    decal(mesh, [(2.6, 10.0, -13.15), (-2.6, 10.0, -13.15),
                 (-2.6, 15.2, -13.15), (2.6, 15.2, -13.15)], "mark", (0, 0, -1))
    return mesh


def make_arm_meshes():
    """Shoulder-local construction arm: drum, upper arm, then a tool forearm."""
    upper = Mesh("spider_upper_arm")
    cylinder(upper, (-1.7, 0, 0), (1.7, 0, 0), 1.9, "body_dark", 6)
    for x in (-1.7, 1.7):
        annulus(upper, (x, 0, 0), (1 if x > 0 else -1, 0, 0), 1.95, 1.2, "steel", 6)
    cylinder(upper, (0, 0, 0), (0, -1.2, 5.8), 1.4, "body", 6, end_radius=1.15)
    plate(upper, [(-1.1, 0.7, 0.8), (1.1, 0.7, 0.8), (1.1, -0.6, 5.0), (-1.1, -0.6, 5.0)],
          0.35, "body_edge", normal=(0, 1, 0.2))

    fore = Mesh("spider_forearm")
    cylinder(fore, (-1.3, 0, 0), (1.3, 0, 0), 1.35, "body_dark", 6)
    cylinder(fore, (0, 0, 0), (0, -2.4, 6.2), 1.05, "body", 6, end_radius=0.75)
    # Welder head: housing, nozzle, amber work light and the emitter ring.
    box(fore, (0, -2.5, 6.7), (2.5, 2.0, 2.6), "body_light")
    cylinder(fore, (0, -2.5, 7.9), (0, -2.5, 8.8), 0.62, "steel", 6)
    annulus(fore, (0, -2.5, 8.85), (0, 0, 1), 0.74, 0.40, "lamp", 6)
    fore.face([(-0.6, -1.7, 7.82), (0.6, -1.7, 7.82),
               (0.6, -1.0, 7.82), (-0.6, -1.0, 7.82)], "glass", outward=(0, 0, 1))
    return upper, fore


def make_model():
    root = Piece("Base", (0, 0, 0), make_hull())
    root.children.extend(make_legs())
    upper, fore = make_arm_meshes()
    for side, label in ((-1, "L"), (1, "R")):
        nano = Piece(f"Nano{label}", (0, -2.5, 8.8))
        forearm = Piece(f"Forearm{label}", (0, -1.2, 5.8), fore, [nano])
        root.children.append(Piece(f"Arm{label}", (side*5.6, 18.0, 8.4), upper, [forearm]))
    return root


def write_rig_data(path):
    lines = [
        "-- Generated by tools/build_spider.py; do not edit.",
        "-- X right, Y up, Z forward. Gait is driven by real displacement.",
        "-- yaw is the leg's resting hip angle; the knee bends about local z.",
        "-- Foot-space stride, fixed tripod offsets and a double-support interval.",
        "return {",
        f"    stride = {STRIDE:.17g},",
        f"    stanceFraction = {STANCE_FRACTION:.17g},",
        f"    knee = {{ x = {KNEE[0]:.17g}, y = {KNEE[1]:.17g} }},",
        f"    foot = {{ x = {FOOT[0]:.17g}, y = {FOOT[1]:.17g} }},",
        f"    hipAmplitude = {HIP_AMPLITUDE:.17g},",
        f"    kneeLift = {KNEE_LIFT:.17g},",
        "    legs = {",
    ]
    for side, label in ((-1, "L"), (1, "R")):
        for index, (z, angle) in enumerate(zip(HIP_Z, SPLAY), 1):
            yaw = (180.0 - angle) if side < 0 else angle
            phase = 0.5 if (index + (0 if side > 0 else 1)) % 2 else 0.0
            lines.append(
                f'        {{ hip = "Hip{label}{index}", knee = "Knee{label}{index}", '
                f'x = {side*HIP_X:.17g}, yaw = {math.radians(yaw):.17g}, '
                f'phase = {phase:.1f} }},')
    lines.extend(("    },", "}", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def patch_s3o_bounds(path, low, high):
    """The exported piece tree is the canonical leg; the header must describe
    the splayed rest pose or the bounding sphere will be too small."""
    import struct
    data = bytearray(path.read_bytes())
    middle = np.asarray((0.0, float(high[1]) * 0.5, 0.0))
    radius = max(np.linalg.norm(np.asarray(corner) - middle) for corner in (low, high))
    struct.pack_into("<f", data, 16, float(radius))
    struct.pack_into("<f", data, 20, float(high[1]))
    struct.pack_into("<3f", data, 24, *[float(v) for v in middle])
    path.write_bytes(data)


def make_previews(model, diffuse, material, directory):
    render(model, diffuse, material, directory/"spider_front.png",
           eye=(96, 62, 104), target=(0, 12, 2))
    render(model, diffuse, material, directory/"spider_rear.png",
           eye=(-100, 58, -96), target=(0, 12, -2))
    side = render(model, diffuse, material, directory/"spider_side.png",
                  eye=(150, 26, 0), target=(0, 12, 0), width=1400, height=700)
    top = render(model, diffuse, material, directory/"spider_top.png",
                 eye=(0, 150, 0), target=(0, 0, 0), width=760, height=900)
    front = render(model, diffuse, material, directory/"spider_front_ortho.png",
                   eye=(0, 16, 150), target=(0, 12, 0), width=760, height=700)
    sheet = Image.new("RGB", (1500, 1600), (226, 230, 221))
    sheet.paste(side.convert("RGB"), (50, 80))
    sheet.paste(front.convert("RGB"), (55, 860))
    sheet.paste(top.resize((560, 780), Image.Resampling.LANCZOS).convert("RGB"), (870, 700))
    font = ImageFont.load_default(size=27)
    draw = ImageDraw.Draw(sheet)
    for text, xy in (("SP-6 ENGINEER / LOW-POLY", (55, 30)), ("SIDE", (55, 100)),
                     ("FRONT", (55, 845)), ("TOP", (870, 710))):
        draw.text(xy, text, fill=(58, 63, 55), font=font)
    sheet.save(directory/"spider_views.png")
    icon = render(model, diffuse, material, directory/"spider_icon_source.png",
                  eye=(100, 70, 108), target=(0, 12, 1), width=512, height=512, transparent=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT/"UnitPics"/"spider.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-preview", action="store_true")
    args = parser.parse_args()
    model = make_model()
    posed = posed_for_preview(model)
    diffuse, material = make_atlas()
    count = sum(len(p.mesh.indices)//3 for p, _ in walk(model) if p.mesh)
    assert count <= TRIANGLE_BUDGET, f"Low-poly budget exceeded: {count} > {TRIANGLE_BUDGET}"
    objects, textures, previews = ROOT/"Objects3d", ROOT/"UnitTextures", ROOT/"tools"/"previews"
    for folder in (objects, textures, previews, ROOT/"Scripts", ROOT/"UnitPics"):
        folder.mkdir(parents=True, exist_ok=True)
    diffuse.save(textures/"spider_diffuse.tga", compression=None)
    material.save(textures/"spider_material.tga", compression=None)
    write_s3o(model, objects/"spider.s3o", textures=("spider_diffuse.tga", "spider_material.tga"))
    low, high = model_bounds(posed)
    patch_s3o_bounds(objects/"spider.s3o", low, high)
    write_glb(model, diffuse, material, objects/"spider.glb", generator="MyGame low-poly SP-6 Engineer")
    write_rig_data(ROOT/"Scripts"/"spider_rig_data.lua")
    manifest = dict(name="SP-6 Engineer", style="flat-shaded low-poly",
                    triangle_budget=TRIANGLE_BUDGET, triangles=count,
                    pieces=[p.name for p, _ in walk(model)],
                    bounds=dict(min=low.tolist(), max=high.tolist()),
                    texture_size=list(diffuse.size), coordinates="X right, Y up, Z forward",
                    native_model="Objects3d/spider.s3o", exchange_model="Objects3d/spider.glb",
                    rig_data="Scripts/spider_rig_data.lua",
                    gait=dict(stride=STRIDE, hipAmplitude=HIP_AMPLITUDE,
                              kneeLift=KNEE_LIFT, legs=6))
    (previews/"spider_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(f"Built SP-6 Engineer: {count} triangles / {len(manifest['pieces'])} pieces", flush=True)
    if not args.no_preview:
        make_previews(posed, diffuse, material, previews)
        print("Rendered front, rear, orthographic views and build icon", flush=True)


if __name__ == "__main__":
    main()
