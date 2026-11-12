"""Build a deliberately low-poly M1A1 Abrams for MyGame.

The supplied 1991 multi-view establishes the silhouette; the stylized tank sets
its detail level. Flat paint, hard normals, eight-sided wheels, and no fine bolts
or ERA blocks. All geometry and artwork are original, generated below.

    python -I tools/build_m1a1.py

Requires the same Pillow/NumPy environment as build_ztz99a.py. Uses that module's
mesh primitives and validated S3O/GLB exporters without rebuilding the ZTZ-99A.
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
                        loft, model_bounds, outline, render, vec, walk, write_glb, write_s3o)

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATLAS_SIZE = 256
TRIANGLE_BUDGET = 3200
COLORS = {
    "sand": (198, 177, 133), "sand_light": (216, 196, 153),
    "sand_dark": (160, 140, 100), "sand_edge": (184, 161, 116),
    "rubber": (30, 33, 33), "track": (63, 64, 59),
    "hub": (190, 170, 126), "black": (17, 23, 24),
    "glass": (64, 108, 115), "steel": (92, 96, 88),
    "lamp": (229, 216, 173), "red": (153, 59, 42),
    "team": (68, 133, 185), "canvas": (132, 123, 94),
}
RECTS = {name: (2+(i % 4)*32, 2+(i//4)*32, 29+(i % 4)*32, 29+(i//4)*32)
         for i, name in enumerate(COLORS)}
RECTS.update(chevron=(132, 4, 252, 124), grille=(4, 132, 124, 252))
WHEEL_Z = (26.4, 17.6, 8.8, 0.0, -8.8, -17.6, -26.4)


class Mesh(BaseMesh):
    """Use this tank's small flat-color atlas, not the 99A camouflage atlas."""

    def face(self, points, material="sand", outward=None, normals=None, uvs=None):
        if uvs is None:
            x0, y0, x1, y1 = RECTS[material]
            uv = ((x0+x1)/(2*ATLAS_SIZE), 1-(y0+y1)/(2*ATLAS_SIZE))
            uvs = [uv]*len(points)
        super().face(points, material, outward, normals, uvs)


def cylinder(mesh, start, end, radius, material="sand", segments=8,
             end_radius=None, caps=True):
    round_cylinder(mesh, start, end, radius, material, segments=segments,
                   end_radius=end_radius, caps=caps, smooth=False)


def decal(mesh, points, material, outward):
    x0, y0, x1, y1 = RECTS[material]
    uvs = [(x0/ATLAS_SIZE, 1-y1/ATLAS_SIZE), (x1/ATLAS_SIZE, 1-y1/ATLAS_SIZE),
           (x1/ATLAS_SIZE, 1-y0/ATLAS_SIZE), (x0/ATLAS_SIZE, 1-y0/ATLAS_SIZE)]
    mesh.face(points, material, outward=outward, uvs=uvs)


def make_atlas():
    diffuse = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), COLORS["sand"]+(0,))
    material = Image.new("RGBA", diffuse.size, (0, 12, 0, 255))
    paint, surface = ImageDraw.Draw(diffuse), ImageDraw.Draw(material)
    for name, color in COLORS.items():
        x0, y0, x1, y1 = RECTS[name]
        rect = (x0-2, y0-2, x1+2, y1+2)
        paint.rectangle(rect, fill=color+(255 if name == "team" else 0,))
        reflection = 35 if name in ("glass", "steel") else 6 if name == "rubber" else 12
        surface.rectangle(rect, fill=(0, reflection, 0, 255))
    # A single large tactical mark, not fine print or a photographed texture.
    paint.rectangle(RECTS["chevron"], fill=COLORS["black"]+(0,))
    surface.rectangle(RECTS["chevron"], fill=(0, 0, 0, 0))
    surface.polygon([(147, 102), (192, 21), (237, 102), (224, 102),
                     (192, 46), (160, 102)], fill=(0, 0, 0, 255))
    for x in (181, 203):
        surface.rectangle((x-4, 105, x+4, 113), fill=(0, 0, 0, 255))
    paint.rectangle(RECTS["grille"], fill=COLORS["sand_dark"]+(0,))
    for y in (146, 168, 190, 212, 234):
        paint.rectangle((12, y, 116, y+10), fill=COLORS["black"]+(0,))
    return diffuse, material


def make_hull():
    mesh = Mesh("m1a1_hull")
    loft(mesh, [(4.7, outline(13.8, -36, 31, 2)),
                (12.7, outline(17.5, -43, 43, 2)),
                (16.8, outline(16.8, -40.8, 26.5, 1.2))], "sand")
    for side in (-1, 1):
        # Large uninterrupted fenders and six broad skirt panels per side.
        box(mesh, (side*18.5, 17.6, -4.4), (6.8, 2.4, 72), "sand_light")
        for index, z in enumerate((-28, -17, -6, 5, 16, 27)):
            color = "sand" if index % 3 else "sand_edge"
            box(mesh, (side*21.35, 13.5, z), (0.8, 10.0, 10.65), color)
        mesh.face([(side*21.77, 8.5, 32.4), (side*21.77, 12.7, 42.3),
                   (side*21.77, 18.8, 31.6), (side*21.77, 18.8, 29.7)],
                  "sand", outward=(side, 0, 0))
        mesh.face([(side*14.8, 18.8, 30.0), (side*21.9, 18.8, 30.0),
                   (side*21.9, 12.9, 42.4), (side*14.8, 12.9, 42.4)],
                  "sand_light", outward=(0, 1, 1))
        mesh.face([(side*14.8, 18.8, 30.0), (side*14.8, 12.9, 42.4),
                   (side*14.8, 12.7, 42.4), (side*14.8, 16.0, 30.0)],
                  "sand_edge", outward=(-side, 0, 0))
        box(mesh, (side*17.5, 8.9, -40.3), (6.8, 6.0, 0.6), "rubber")
        box(mesh, (side*18.9, 18.3, 32.3), (3.0, 1.8, 2.5), "sand_dark")
        mesh.face([(side*18.9-0.9, 17.75, 33.56), (side*18.9+0.9, 17.75, 33.56),
                   (side*18.9+0.9, 18.75, 33.56), (side*18.9-0.9, 18.75, 33.56)],
                  "lamp", outward=(0, 0, 1))
        points = [(side*21.77, 10.2, 8.7), (side*21.77, 10.2, 1.3),
                  (side*21.77, 18.3, 1.3), (side*21.77, 18.3, 8.7)]
        if side < 0:
            points = [points[1], points[0], points[3], points[2]]
        decal(mesh, points, "chevron", (side, 0, 0))
    # A few painted vent slots replace dozens of modeled louvers.
    # The rear engine deck sits higher than the deck under the turret ring.
    box(mesh, (0, 17.6, -31.6), (31, 3.0, 18.4), "sand_dark")
    decal(mesh, [(-12.5, 19.11, -24.6), (12.5, 19.11, -24.6),
                 (12.5, 19.11, -38.6), (-12.5, 19.11, -38.6)], "grille", (0, 1, 0))
    box(mesh, (0, 15.0, -42.1), (28.8, 6.6, 2.1), "sand_dark")
    decal(mesh, [(13.5, 12.3, -43.16), (-13.5, 12.3, -43.16),
                 (-13.5, 17.7, -43.16), (13.5, 17.7, -43.16)], "grille", (0, 0, -1))
    for x in (-17, 17):
        box(mesh, (x, 17.3, -41.7), (2.4, 1.2, 0.6), "red")
    cylinder(mesh, (0, 16.8, 23.0), (0, 17.4, 23.0), 2.9, "sand_edge")
    box(mesh, (0, 17.8, 24.1), (3.7, 0.7, 1.0), "black")
    return mesh


def make_turret():
    mesh = Mesh("m1a1_turret")
    cylinder(mesh, (0, -0.2, 0), (0, 1.6, 0), 12.5, "sand_dark", 12)
    lower = [(-13.7, -23.0), (13.7, -23.0), (15.7, -20.8), (16.2, 3.2),
             (7.6, 17.2), (-7.6, 17.2), (-16.2, 3.2), (-15.7, -20.8)]
    waist = [(-15.6, -25.0), (15.6, -25.0), (17.5, -22.3), (18.0, 3.6),
             (7.8, 19.0), (-7.8, 19.0), (-18.0, 3.6), (-17.5, -22.3)]
    roof = [(-14.6, -24.0), (14.6, -24.0), (15.5, -22.1), (15.5, 4.0),
            (6.7, 13.3), (-6.7, 13.3), (-15.5, 4.0), (-15.5, -22.1)]
    loft(mesh, [(1.3, lower), (3.5, waist), (10.5, roof)], "sand")
    for x in (-7.3, 7.3):
        box(mesh, (x, 10.59, -13.3), (13.5, 0.16, 14.0), "sand_light")
    # The long rear bustle is a silhouette feature; the basket stays coarse.
    box(mesh, (0, 7.6, -26.8), (30.7, 4.8, 6.0), "canvas")
    for y in (5.5, 10.3):
        box(mesh, (0, y, -30.0), (33.0, 0.7, 0.7), "sand_dark")
    for x in (-16.2, -5.4, 5.4, 16.2):
        box(mesh, (x, 7.9, -30.0), (0.65, 4.8, 0.7), "sand_edge")
    for side in (-1, 1):
        box(mesh, (side*16.2, 10.3, -26.0), (0.7, 0.7, 8.0), "sand_dark")
        box(mesh, (side*11.8, 8.0, -30.4), (3.3, 2.2, 0.12), "team")
        box(mesh, (side*17.3, 6.8, 0.7), (2.3, 2.5, 5.5), "sand_dark")
        for z in (-0.9, 0.7, 2.3):
            mesh.face([(side*18.46, 6.0, z-0.48), (side*18.46, 6.0, z+0.48),
                       (side*18.46, 7.5, z+0.48), (side*18.46, 7.5, z-0.48)],
                      "black", outward=(side, 0, 0))
        cylinder(mesh, (side*12.1, 10.5, -20.0),
                 (side*12.1, 25.0 if side > 0 else 22.0, -20.0), 0.14,
                 "black", segments=4, end_radius=0.08)
    # M1A1 roof: two hatches and a box sight, no M1A2 panoramic-sight tower.
    cylinder(mesh, (6.9, 10.5, -1.9), (6.9, 12.1, -1.9), 3.6, "sand_dark")
    cylinder(mesh, (6.9, 12.1, -1.9), (6.9, 12.6, -1.9), 3.2, "sand_light")
    cylinder(mesh, (-6.7, 10.5, -0.8), (-6.7, 11.3, -0.8), 3.2, "sand_edge")
    box(mesh, (8.6, 12.0, 7.0), (4.5, 3.0, 3.7), "sand_dark")
    mesh.face([(6.9, 11.4, 8.86), (10.3, 11.4, 8.86),
               (10.3, 12.9, 8.86), (6.9, 12.9, 8.86)], "glass", outward=(0, 0, 1))
    box(mesh, (6.9, 14.0, -0.3), (0.8, 3.0, 0.8), "steel")
    box(mesh, (6.9, 15.6, 0.8), (1.3, 1.4, 4.3), "black")
    cylinder(mesh, (6.9, 15.7, 2.95), (6.9, 15.7, 10.8), 0.28, "black", 6)
    box(mesh, (5.3, 15.3, 0.6), (1.8, 1.8, 2.4), "sand_dark")
    scale = np.asarray((1, 0.9, 1))
    mesh.positions = (np.asarray(mesh.positions)*scale).tolist()
    normals = np.asarray(mesh.normals)/scale
    mesh.normals = (normals/np.linalg.norm(normals, axis=1, keepdims=True)).tolist()
    return mesh


def make_gun():
    mesh = Mesh("m1a1_gun")
    loft(mesh, [(-2.5, outline(3.7, -1.5, 4.0, 0.6)),
                (2.5, outline(3.3, -1.5, 3.0, 0.6))], "sand_dark")
    cylinder(mesh, (0, 0, 2.8), (0, 0, 6.3), 1.75, "sand_edge")
    cylinder(mesh, (0, 0, 6.3), (0, 0, 20.0), 1.15, "sand_light")
    cylinder(mesh, (0, 0, 20.0), (0, 0, 22.0), 1.15, "sand", end_radius=1.75)
    cylinder(mesh, (0, 0, 22.0), (0, 0, 26.0), 1.75, "sand")
    cylinder(mesh, (0, 0, 26.0), (0, 0, 28.0), 1.75, "sand", end_radius=1.05)
    cylinder(mesh, (0, 0, 28.0), (0, 0, 54.8), 1.05, "sand_light", caps=False)
    cylinder(mesh, (0, 0, 39.5), (0, 0, 40.1), 1.1, "sand_dark", caps=False)
    annulus(mesh, (0, 0, 54.8), (0, 0, 1), 1.05, 0.72, "sand_edge", segments=8)
    cylinder(mesh, (0, 0, 54.2), (0, 0, 54.25), 0.73, "black")
    return mesh


def wheel_mesh(name, radius):
    mesh = Mesh(name)
    cylinder(mesh, (-2.35, 0, 0), (2.35, 0, 0), radius, "rubber")
    for side in (-1, 1):
        # Broad octagonal disks read at RTS scale; no bolts, holes, or tiny spokes.
        x = side*2.38
        points = [(x, radius*0.78*math.cos(i*math.tau/8),
                   radius*0.78*math.sin(i*math.tau/8)) for i in range(8)]
        mesh.face(points, "hub", outward=(side, 0, 0))
        hub = [(side*2.42, radius*0.27*math.cos(i*math.tau/6),
                radius*0.27*math.sin(i*math.tau/6)) for i in range(6)]
        mesh.face(hub, "sand_dark", outward=(side, 0, 0))
    return mesh


def track_pose(data, distance):
    s = distance % data["perimeter"]
    h, r, cy = data["halfStraight"], data["radius"], data["centerY"]
    if s < 2*h:
        return vec((0, cy+r, -h+s)), 0.0
    s -= 2*h
    if s < math.pi*r:
        angle = s/r
        return vec((0, cy+r*math.cos(angle), h+r*math.sin(angle))), angle
    s -= math.pi*r
    if s < 2*h:
        return vec((0, cy-r, h-s)), math.pi
    angle = math.pi+(s-2*h)/r
    return vec((0, cy+r*math.cos(angle), -h+r*math.sin(angle))), angle


def make_track_data():
    data = dict(linkCount=40, wheelCount=7, halfStraight=32.0, radius=7.0,
                centerY=7.8, halfWidth=17.4, wheelRadius=4.15, idlerRadius=4.1,
                idlerY=8.9, idlerZ=34.2, pieceCount=102)
    data["perimeter"] = 4*data["halfStraight"]+math.tau*data["radius"]
    data["links"] = []
    for i in range(1, data["linkCount"]+1):
        phase = (i-0.5)*data["perimeter"]/data["linkCount"]
        point, angle = track_pose(data, phase)
        data["links"].append(dict(phase=phase, y=float(point[1]), z=float(point[2]),
                                  angle=angle, left=f"TrackL{i:02d}", right=f"TrackR{i:02d}"))
    return data


def make_tracks(data):
    template = Mesh("m1a1_track_link")
    length = 0.98*data["perimeter"]/data["linkCount"]
    box(template, (0, 0, 0), (6.8, 0.65, length), "track")
    template.face([(-2.3, 0.331, -length*0.32), (2.3, 0.331, -length*0.32),
                   (2.3, 0.331, length*0.32), (-2.3, 0.331, length*0.32)],
                  "rubber", outward=(0, 1, 0))
    meshes, pieces = {}, []
    idler = wheel_mesh("m1a1_end_wheel", data["idlerRadius"])
    for side, label, key in ((-1, "L", "left"), (1, "R", "right")):
        for rest in data["links"]:
            angle = rest["angle"]
            if angle not in meshes:
                c, s = math.cos(angle), math.sin(angle)
                axes = np.asarray(((1, 0, 0), (0, c, s), (0, -s, c)))
                meshes[angle] = Mesh(f"m1a1_shoe_pose_{len(meshes):02d}",
                    positions=(np.asarray(template.positions) @ axes).tolist(),
                    normals=(np.asarray(template.normals) @ axes).tolist(),
                    uvs=template.uvs, indices=template.indices)
            pieces.append(Piece(rest[key], (side*data["halfWidth"], rest["y"], rest["z"]), meshes[angle]))
        for end, sign in (("Front", 1), ("Rear", -1)):
            pieces.append(Piece(f"Idler{label}{end}",
                (side*data["halfWidth"], data["idlerY"], sign*data["idlerZ"]), idler))
    return pieces


def make_model(data=None):
    data = make_track_data() if data is None else data
    gun = Piece("Gun", (0, 5.4, 15.0), make_gun(), [Piece("Flare", (0, 0, 54.8))])
    turret = Piece("Turret", (0, 16.9, 1.5), make_turret(), [gun])
    root = Piece("Base", (0, 0, 0), make_hull(), [turret])
    wheel = wheel_mesh("m1a1_road_wheel", data["wheelRadius"])
    for side, label in ((-1, "L"), (1, "R")):
        for i, z in enumerate(WHEEL_Z, 1):
            root.children.append(Piece(f"Wheel{label}{i}", (side*data["halfWidth"], 5.25, z), wheel))
    root.children.extend(make_tracks(data))
    return root


def write_track_data(data, path):
    lines = ["-- Generated by tools/build_m1a1.py; do not edit.",
             "-- X right, Y up, Z forward; rest X rotations are baked into the shoes.", "return {"]
    for key, value in data.items():
        if key != "links":
            lines.append(f"    {key} = {value:.17g},")
    lines.append("    links = {")
    for link in data["links"]:
        fields = ", ".join(f"{key} = {link[key]:.17g}" for key in ("phase", "y", "z", "angle"))
        lines.append(f'        {{ {fields}, left = "{link["left"]}", right = "{link["right"]}" }},')
    lines.extend(("    },", "}", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def make_previews(model, diffuse, material, directory):
    render(model, diffuse, material, directory/"m1a1_front.png", eye=(125, 91, 148))
    render(model, diffuse, material, directory/"m1a1_rear.png", eye=(-130, 83, -148))
    side = render(model, diffuse, material, directory/"m1a1_side.png", eye=(180, 20, 0),
                  target=(0, 20, 0), width=1400, height=670)
    front = render(model, diffuse, material, directory/"m1a1_front_ortho.png", eye=(0, 20, 180),
                   target=(0, 20, 0), width=680, height=670)
    top = render(model, diffuse, material, directory/"m1a1_top.png", eye=(0, 180, 0),
                 target=(0, 0, 0), width=680, height=1000)
    sheet = Image.new("RGB", (1500, 1620), (226, 230, 221))
    sheet.paste(side.convert("RGB"), (50, 80))
    sheet.paste(front.convert("RGB"), (55, 880))
    sheet.paste(top.resize((612, 900), Image.Resampling.LANCZOS).convert("RGB"), (815, 700))
    font = ImageFont.load_default(size=27)
    draw = ImageDraw.Draw(sheet)
    for text, xy in (("M1A1 / LOW-POLY", (55, 30)), ("SIDE", (55, 100)),
                     ("FRONT", (55, 865)), ("TOP", (815, 710))):
        draw.text(xy, text, fill=(58, 63, 55), font=font)
    sheet.save(directory/"m1a1_views.png")
    icon = render(model, diffuse, material, directory/"m1a1_icon_source.png",
                  width=512, height=512, transparent=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT/"UnitPics"/"m1a1.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-preview", action="store_true")
    args = parser.parse_args()
    data = make_track_data()
    model = make_model(data)
    diffuse, material = make_atlas()
    count = sum(len(p.mesh.indices)//3 for p, _ in walk(model) if p.mesh)
    assert count <= TRIANGLE_BUDGET, f"Low-poly budget exceeded: {count} > {TRIANGLE_BUDGET}"
    objects, textures, previews = ROOT/"Objects3d", ROOT/"UnitTextures", ROOT/"tools"/"previews"
    for folder in (objects, textures, previews, ROOT/"Scripts", ROOT/"UnitPics"):
        folder.mkdir(parents=True, exist_ok=True)
    diffuse.save(textures/"m1a1_diffuse.tga", compression=None)
    material.save(textures/"m1a1_material.tga", compression=None)
    write_s3o(model, objects/"m1a1.s3o", textures=("m1a1_diffuse.tga", "m1a1_material.tga"))
    write_glb(model, diffuse, material, objects/"m1a1.glb", generator="MyGame low-poly M1A1 Abrams")
    write_track_data(data, ROOT/"Scripts"/"m1a1_track_data.lua")
    low, high = model_bounds(model)
    manifest = dict(name="M1A1 Abrams", style="flat-shaded low-poly", triangle_budget=TRIANGLE_BUDGET,
                    triangles=count, pieces=[p.name for p, _ in walk(model)],
                    bounds=dict(min=low.tolist(), max=high.tolist()), texture_size=list(diffuse.size),
                    coordinates="X right, Y up, Z forward", native_model="Objects3d/m1a1.s3o",
                    exchange_model="Objects3d/m1a1.glb", track_data="Scripts/m1a1_track_data.lua", track=data)
    (previews/"m1a1_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(f"Built M1A1: {count} triangles / {len(manifest['pieces'])} pieces", flush=True)
    if not args.no_preview:
        make_previews(model, diffuse, material, previews)
        print("Rendered front, rear, orthographic views and build icon", flush=True)


if __name__ == "__main__":
    main()
