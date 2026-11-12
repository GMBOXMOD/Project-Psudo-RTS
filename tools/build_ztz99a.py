"""Build the MyGame ZTZ-99A-inspired game asset, without a 3D editor.

Requires Pillow and NumPy. Coordinates are X=right, Y=up, Z=forward, matching
Spring's native S3O models. The GLB uses the same geometry and an embedded PNG.
All artwork is generated here; the reference photograph is not used as a texture.

    python -I tools/build_ztz99a.py

Outputs native S3O, editable GLB, two S3O texture atlases, a build icon, studio
previews and the unit script's track animation data. It does not touch the previous
MBT.glb or MBTtexture.tga.
"""

import argparse
import io
import json
import math
import pathlib
import random
import struct
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = pathlib.Path(__file__).resolve().parents[1]
TAU = math.tau
TRACK_LINK_COUNT = 84
TRACK_HALF_STRAIGHT = 31.0
TRACK_RADIUS = 7.0
TRACK_CENTER_Y = 7.6
TRACK_HALF_WIDTH = 17.8
TRACK_PERIMETER = 4 * TRACK_HALF_STRAIGHT + TAU * TRACK_RADIUS
WHEEL_RADIUS = 5.12
WHEEL_Z = (24.5, 14.7, 4.9, -4.9, -14.7, -24.5)
IDLER_RADIUS = 4.1
ATLAS_SIZE = 1024
CAMO_RECT = (4, 4, 508, 508)
COLORS = {
    "olive": (89, 103, 72), "darkolive": (53, 65, 46),
    "steel": (107, 115, 103), "edge": (151, 156, 132),
    "rubber": (26, 31, 28), "track": (66, 73, 63),
    "hub": (109, 121, 86), "black": (13, 19, 18),
    "glass": (48, 128, 150), "glassdark": (16, 48, 54),
    "red": (151, 42, 34), "white": (225, 225, 205),
    "team": (68, 133, 185), "lamp": (235, 222, 168),
    "bore": (7, 11, 10), "canvas": (119, 119, 83),
}
RECTS = {name: (512 + (i % 4) * 128 + 4, (i // 4) * 128 + 4,
                512 + (i % 4) * 128 + 124, (i // 4) * 128 + 124)
         for i, name in enumerate(COLORS)}
RECTS.update(number=(8, 520, 504, 680), star=(520, 520, 760, 760))


def vec(value):
    return np.asarray(value, dtype=np.float64)


def unit(value):
    value = vec(value)
    return value / max(np.linalg.norm(value), 1e-12)


def polygon_normal(points):
    return unit(np.cross(vec(points[1]) - points[0], vec(points[2]) - points[0]))


def make_atlas():
    rng = random.Random(99)
    image = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (89, 103, 72, 0))
    draw = ImageDraw.Draw(image)
    palette = [(91, 106, 75), (61, 76, 53), (143, 143, 104),
               (39, 49, 40), (111, 124, 86)]
    draw.rectangle((0, 0, 511, 511), fill=palette[0] + (0,))
    for color, count in ((palette[1], 80), (palette[2], 38),
                         (palette[3], 32), (palette[4], 38)):
        for _ in range(count * 3):
            x, y = rng.randrange(128) * 4, rng.randrange(128) * 4
            for _ in range(rng.randrange(3, 9)):
                w, h = rng.randrange(1, 5) * 4, rng.randrange(1, 4) * 4
                draw.rectangle((max(0, x), max(0, y), min(511, x+w), min(511, y+h)),
                               fill=color + (0,))
                x = max(0, min(504, x + rng.choice((-8, -4, 4, 8))))
                y = max(0, min(504, y + rng.choice((-8, -4, 4, 8))))
    for name, color in COLORS.items():
        x0, y0, x1, y1 = RECTS[name]
        draw.rectangle((x0-4, y0-4, x1+4, y1+4), fill=color + (255 if name == "team" else 0,))
    # Sparse paint grain, not a repeated photograph or borrowed texture.
    data = np.asarray(image).copy()
    noise = np.random.default_rng(99).integers(-3, 4, size=(1024, 1024, 1))
    data[:, :, :3] = np.clip(data[:, :, :3].astype(np.int16) + noise, 0, 255)
    image = Image.fromarray(data)
    visibility = Image.new("L", image.size, 255)
    mask = ImageDraw.Draw(visibility)
    mask.rectangle(RECTS["number"], fill=0)
    mask.rectangle(RECTS["star"], fill=0)
    draw = ImageDraw.Draw(image)
    draw.rectangle(RECTS["number"], fill=COLORS["white"] + (0,))
    font_path = pathlib.Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 142) if font_path.exists() else ImageFont.load_default(size=130)
    mask.text((253, 602), "101", fill=255, font=font, anchor="mm", stroke_width=1)
    # The second atlas cuts out the decal background; no camouflage rectangle.
    mask.rectangle((251, 541, 254, 661), fill=0)
    mask.rectangle((352, 541, 355, 661), fill=0)
    draw.rectangle((520, 520, 760, 760), fill=COLORS["darkolive"] + (0,))
    star = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = 108 if i % 2 == 0 else 45
        star.append((640 + math.cos(angle)*r, 640 + math.sin(angle)*r))
    draw.polygon(star, fill=(191, 164, 63, 0))
    mask.polygon(star, fill=255)
    star = [(640+(x-640)*0.85, 640+(y-640)*0.85) for x, y in star]
    draw.polygon(star, fill=(166, 47, 34, 0))
    chinese = pathlib.Path("C:/Windows/Fonts/msyh.ttc")
    if chinese.exists():
        draw.text((640, 642), "八一", font=ImageFont.truetype(str(chinese), 38),
                  fill=(232, 199, 99, 0), anchor="mm")
    # S3O tex2: R=emission, G=reflection/specular, A=visibility.
    extra = Image.new("RGBA", image.size, (0, 22, 0, 255))
    ed = ImageDraw.Draw(extra)
    for name, reflection, glow in (("rubber", 4, 0), ("track", 35, 0), ("steel", 68, 0),
                                    ("edge", 70, 0), ("glass", 105, 12), ("glassdark", 70, 0),
                                    ("lamp", 45, 50), ("red", 24, 8), ("bore", 0, 0)):
        x0, y0, x1, y1 = RECTS[name]
        ed.rectangle((x0-4, y0-4, x1+4, y1+4), fill=(glow, reflection, 0, 255))
    extra.putalpha(visibility)
    return image, extra


def texture_uv(point, normal, material, origin):
    if material == "camo":
        x, y, z = vec(point) + origin
        axis = int(np.argmax(np.abs(normal)))
        a, b = ((z, y), (x, z), (x, y))[axis]
        u, v = (a + 80) / 160, (b + 80) / 160
        x0, y0, x1, y1 = CAMO_RECT
        return ((x0 + u*(x1-x0)) / ATLAS_SIZE,
                1 - (y0 + v*(y1-y0)) / ATLAS_SIZE)
    x0, y0, x1, y1 = RECTS[material]
    return ((x0+x1) / (2*ATLAS_SIZE), 1 - (y0+y1) / (2*ATLAS_SIZE))


@dataclass
class Mesh:
    name: str
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    positions: list = field(default_factory=list)
    normals: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    indices: list = field(default_factory=list)

    def face(self, points, material="camo", outward=None, normals=None, uvs=None):
        points = [vec(p) for p in points]
        n = polygon_normal(points)
        if outward is not None and np.dot(n, outward) < 0:
            points.reverse()
            n = -n
            if normals is not None:
                normals = list(reversed(normals))
            if uvs is not None:
                uvs = list(reversed(uvs))
        start = len(self.positions)
        for i, p in enumerate(points):
            self.positions.append(tuple(p))
            self.normals.append(tuple(normals[i] if normals is not None else n))
            self.uvs.append(tuple(uvs[i] if uvs is not None else texture_uv(p, n, material, self.origin)))
        for i in range(1, len(points)-1):
            self.indices.extend((start, start+i, start+i+1))

    def solid(self, vertices, faces, material="camo"):
        center = np.mean(vertices, axis=0)
        for indices in faces:
            points = [vec(vertices[i]) for i in indices]
            self.face(points, material, np.mean(points, axis=0)-center)


BOX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))


def box(mesh, center, size, material="camo", axes=None):
    c, s = vec(center), vec(size)*0.5
    a = np.eye(3) if axes is None else np.asarray(axes)
    signs = ((-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1),
             (-1,1,-1),(1,1,-1),(1,1,1),(-1,1,1))
    vertices = [c + (vec(q)*s) @ a for q in signs]
    mesh.solid(vertices, BOX_FACES, material)


def outline(width, rear, front, bevel=2):
    return [(-width+bevel, rear), (width-bevel, rear), (width, rear+bevel),
            (width, front-bevel), (width-bevel, front), (-width+bevel, front),
            (-width, front-bevel), (-width, rear+bevel)]


def loft(mesh, layers, material="camo"):
    vertices = [vec((x,y,z)) for y, ring in layers for x,z in ring]
    n = len(layers[0][1])
    faces = [tuple(range(n-1, -1, -1)), tuple(range((len(layers)-1)*n, len(vertices)))]
    for layer in range(len(layers)-1):
        for i in range(n):
            j = (i+1) % n
            faces.append((layer*n+i, layer*n+j, (layer+1)*n+j, (layer+1)*n+i))
    mesh.solid(vertices, faces, material)


def bevel_box(mesh, center, size, bevel=0.35, material="camo"):
    x, y, z = center
    w, h, d = np.asarray(size)*0.5
    rings = [(y-h, outline(w-bevel, z-d+bevel, z+d-bevel, bevel)),
             (y-h+bevel, outline(w, z-d, z+d, bevel)),
             (y+h-bevel, outline(w, z-d, z+d, bevel)),
             (y+h, outline(w-bevel, z-d+bevel, z+d-bevel, bevel))]
    loft(mesh, [(height, [(px+x,pz) for px,pz in ring]) for height,ring in rings], material)


def cylinder(mesh, start, end, radius, material="olive", segments=16,
             end_radius=None, caps=True, smooth=True):
    start, end = vec(start), vec(end)
    axis = unit(end-start)
    ref = (1,0,0) if abs(axis[1]) > 0.95 else (0,1,0)
    u = unit(np.cross(axis, ref))
    v = np.cross(axis, u)
    end_radius = radius if end_radius is None else end_radius
    directions = [u*math.cos(TAU*i/segments) + v*math.sin(TAU*i/segments) for i in range(segments)]
    ring1 = [start+r*radius for r in directions]
    ring2 = [end+r*end_radius for r in directions]
    slope = (radius-end_radius) / max(np.linalg.norm(end-start), 1e-9)
    ns = [unit(r+axis*slope) for r in directions]
    for i in range(segments):
        j = (i+1) % segments
        normals = [ns[i],ns[j],ns[j],ns[i]] if smooth else None
        mesh.face([ring1[i],ring1[j],ring2[j],ring2[i]], material,
                  directions[i]+directions[j], normals)
    if caps:
        mesh.face(ring1, material, -axis)
        mesh.face(ring2, material, axis)


def annulus(mesh, center, axis, outer, inner, material="steel", segments=20):
    center, axis = vec(center), unit(axis)
    u = unit(np.cross(axis, (1,0,0) if abs(axis[1]) > 0.95 else (0,1,0)))
    v = np.cross(axis, u)
    ring = [u*math.cos(TAU*i/segments)+v*math.sin(TAU*i/segments) for i in range(segments)]
    for i in range(segments):
        a,b = ring[i],ring[(i+1) % segments]
        mesh.face([center+a*outer,center+b*outer,center+b*inner,center+a*inner], material, axis)


def tube(mesh, points, radius, material="steel", segments=8):
    for a,b in zip(points, points[1:]):
        cylinder(mesh, a, b, radius, material, segments)


def plate(mesh, points, depth=0.55, material="camo", normal=None):
    points = [vec(p) for p in points]
    normal = polygon_normal(points) if normal is None else unit(normal)
    vertices = points + [p+normal*depth for p in points]
    mesh.solid(vertices, BOX_FACES, material)


def panel_grid(mesh, corners, rows, columns, depth=0.4):
    p0,p1,p2,p3 = [vec(p) for p in corners]
    normal = polygon_normal(corners)
    def point(u,v):
        return (1-v)*((1-u)*p0+u*p1) + v*((1-u)*p3+u*p2)
    for row in range(rows):
        for column in range(columns):
            u0,u1 = (column+0.035)/columns, (column+0.965)/columns
            v0,v1 = (row+0.055)/rows, (row+0.945)/rows
            plate(mesh, [point(u0,v0),point(u1,v0),point(u1,v1),point(u0,v1)], depth, normal=normal)


def decal(mesh, points, name, normal):
    x0,y0,x1,y1 = RECTS[name]
    uv = [(x0/1024,1-y1/1024),(x1/1024,1-y1/1024),
          (x1/1024,1-y0/1024),(x0/1024,1-y0/1024)]
    mesh.face(points, uvs=uv, outward=normal)


def make_wheel():
    mesh = Mesh("road_wheel")
    cylinder(mesh, (-1.8,0,0),(1.8,0,0),WHEEL_RADIUS,"rubber",24)
    cylinder(mesh, (-1.88,0,0),(1.88,0,0),4.42,"hub",24)
    for side in (-1,1):
        x = side*1.92
        annulus(mesh,(x,0,0),(side,0,0),4.48,4.13,"edge",24)
        annulus(mesh,(x+side*0.03,0,0),(side,0,0),3.68,3.42,"darkolive",24)
        cylinder(mesh,(side*1.95,0,0),(side*2.28,0,0),1.55,"olive",16)
        cylinder(mesh,(side*2.29,0,0),(side*2.36,0,0),0.8,"steel",12)
        for i in range(8):
            a = i*TAU/8
            y,z = 2.55*math.sin(a),2.55*math.cos(a)
            cylinder(mesh,(x,y,z),(x+side*0.08,y,z),0.52,"darkolive",8)
            cylinder(mesh,(x+side*0.1,y,z),(x+side*0.28,y,z),0.21,"steel",6)
    return mesh


def track_pose(distance):
    """Closed centerline and right-handed X angle; local +Y is outward, +Z tangent."""
    distance %= TRACK_PERIMETER
    length, radius, cy = 2 * TRACK_HALF_STRAIGHT, TRACK_RADIUS, TRACK_CENTER_Y
    arc = math.pi * radius
    if distance < length:
        return vec((0, cy + radius, -TRACK_HALF_STRAIGHT + distance)), 0.0
    distance -= length
    if distance < arc:
        angle = distance / radius
        return vec((0, cy + radius * math.cos(angle),
                    TRACK_HALF_STRAIGHT + radius * math.sin(angle))), angle
    distance -= arc
    if distance < length:
        return vec((0, cy - radius, TRACK_HALF_STRAIGHT - distance)), math.pi
    distance -= length
    angle = math.pi + distance / radius
    return vec((0, cy + radius * math.cos(angle),
                -TRACK_HALF_STRAIGHT + radius * math.sin(angle))), angle


def track_point(distance):
    point, angle = track_pose(distance)
    return point, vec((0, -math.sin(angle), math.cos(angle)))


def make_track_data():
    links = []
    for i in range(1, TRACK_LINK_COUNT + 1):
        phase = (i - 0.5) * TRACK_PERIMETER / TRACK_LINK_COUNT
        point, angle = track_pose(phase)
        links.append({"phase": phase, "y": float(point[1]), "z": float(point[2]),
                      "angle": angle, "left": f"TrackL{i:02d}", "right": f"TrackR{i:02d}"})
    return {"linkCount": TRACK_LINK_COUNT, "halfStraight": TRACK_HALF_STRAIGHT,
            "radius": TRACK_RADIUS, "centerY": TRACK_CENTER_Y, "halfWidth": TRACK_HALF_WIDTH,
            "perimeter": TRACK_PERIMETER, "wheelRadius": WHEEL_RADIUS, "idlerRadius": IDLER_RADIUS,
            "pieceCount": 4 + 2 * len(WHEEL_Z) + 2 * TRACK_LINK_COUNT + 4, "links": links}


def make_track_link():
    # Canonical axes: X across the shoe, Y outward, Z along increasing phase.
    mesh = Mesh("track_link")
    box(mesh, (0,0,0), (7.1,0.5,1.83), "track")
    box(mesh, (0,0.31,0), (4.8,0.22,1.25), "rubber")
    box(mesh, (0,0.36,0.72), (7.35,0.28,0.25), "edge")
    return mesh


def make_idler():
    mesh = Mesh("idler")
    cylinder(mesh, (-2.0,0,0), (2.0,0,0), IDLER_RADIUS, "darkolive", 20)
    for side in (-1,1):
        face_x = side * 2.1
        annulus(mesh, (face_x,0,0), (side,0,0), 3.8, 2.6, "track", 20)
        cylinder(mesh, (face_x,0,0), (face_x+side*0.15,0,0), 1.5, "steel", 12)
        for j in range(10):
            angle = j * TAU / 10
            y, z = 3.1 * math.sin(angle), 3.1 * math.cos(angle)
            cylinder(mesh, (face_x,y,z), (face_x+side*0.12,y,z), 0.35, "black", 6)
    return mesh


def make_tracks(data):
    template, idler = make_track_link(), make_idler()
    meshes, pieces = {}, []
    for side, label, key in ((-1,"L","left"), (1,"R","right")):
        for link in data["links"]:
            angle = link["angle"]
            if angle not in meshes:
                c, s = math.cos(angle), math.sin(angle)
                axes = np.asarray(((1,0,0), (0,c,s), (0,-s,c)))
                # S3O has no rest rotation. Bake it into local positions AND normals,
                # so the script only applies angle-restAngle and center-restCenter.
                # Both sides and straight runs share meshes, but distinct angles
                # must have distinct names because the GLB writer keys by name.
                meshes[angle] = Mesh(f"track_link_pose_{len(meshes):02d}",
                    positions=(np.asarray(template.positions) @ axes).tolist(),
                    normals=(np.asarray(template.normals) @ axes).tolist(),
                    uvs=template.uvs, indices=template.indices)
            pieces.append(Piece(link[key], (side*data["halfWidth"],link["y"],link["z"]), meshes[angle]))
        for end, z in (("Front",33.3), ("Rear",-33.3)):
            pieces.append(Piece(f"Idler{label}{end}", (side*data["halfWidth"],8.9,z), idler))
    return pieces


def write_track_data(data, path):
    lines = ["-- Generated by tools/build_ztz99a.py; do not edit.",
             "-- X right, Y up, Z forward; +phase runs forward on top.",
             "-- Rest X rotations are baked into the meshes; animate angle - rest angle.",
             "return {"]
    for key, value in data.items():
        if key != "links":
            lines.append(f"    {key} = {value:.17g},")
    lines.append("    links = {")
    for link in data["links"]:
        numbers = ", ".join(f"{key} = {link[key]:.17g}" for key in ("phase","y","z","angle"))
        lines.append(f'        {{ {numbers}, left = "{link["left"]}", right = "{link["right"]}" }},')
    lines.extend(("    },", "}", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def make_hull():
    mesh=Mesh("hull")
    loft(mesh,[(4,outline(13.8,-34,33,4)),(10.8,outline(18,-38,40,5)),
               (20,outline(17.2,-36,27.5,3))])
    bevel_box(mesh,(0,17,-6),(33.5,7,52),0.6)
    # Glacis ERA blocks follow the sloping plate, not a horizontal box stack.
    panel_grid(mesh,[(-14.8,19.9,28),(14.8,19.9,28),(14.8,11.25,39.3),(-14.8,11.25,39.3)],2,5,0.65)
    for side in (-1,1):
        # Six independent skirt sections reveal the lower road wheels.
        for z in (-27.5,-16.5,-5.5,5.5,16.5,27.5):
            bevel_box(mesh,(side*21.1,14.4,z),(1.0,11.0,10.65),0.18)
            for dz in (-4.4,4.4):
                cylinder(mesh,(side*21.65,18.5,z+dz),(side*21.85,18.5,z+dz),0.21,"steel",6)
            box(mesh,(side*21.65,10.65,z-2.8),(0.06,0.95,1.35),"black")
        bevel_box(mesh,(side*20.0,20.2,0),(4.8,2.0,69.5),0.35)
        for z in range(-30,34,5):
            box(mesh,(side*20.4,21.23,z),(3.1,0.13,0.20),"darkolive")
        # Rounded-looking front fender and flexible mud flap.
        x0,x1=side*14.5,side*22.2
        plate(mesh,[(x0,19.8,29),(x1,19.8,29),(x1,8.1,41.4),(x0,8.1,41.4)],0.55,normal=(0,0.73,0.68))
        box(mesh,(side*18.4,5.5,41.2),(7.3,5.4,0.6),"rubber")
        box(mesh,(side*18.1,6.5,-38.3),(7.0,5.0,0.7),"rubber")
        # Headlight housings and protective rail.
        bevel_box(mesh,(side*13.7,16.3,35.0),(3.3,2.5,2.6),0.25,"darkolive")
        cylinder(mesh,(side*13.7,16.35,36.30),(side*13.7,16.35,36.55),0.9,"lamp",16)
        tube(mesh,[(side*15.8,15,36.4),(side*15.8,18.1,36.4),
                   (side*11.8,18.1,36.4),(side*11.8,15,36.4)],0.16,"steel")
        cylinder(mesh,(side*10.8,7.7,38.5),(side*10.8,7.7,40.4),0.62,"track",10)
        annulus(mesh,(side*10.8,7.7,40.5),(0,0,1),1.1,0.55,"steel",12)
        box(mesh,(side*15.0,13.5,-38.7),(2.7,1.2,0.35),"red")
    cylinder(mesh,(-3.8,20.1,23.0),(-3.8,20.7,23.0),3.6,"olive",16)
    for x in (-5.6,-3.8,-2.0):
        bevel_box(mesh,(x,21.2,24.4),(1.4,0.8,1.1),0.1,"darkolive")
        box(mesh,(x,21.35,25.02),(1.0,0.4,0.08),"glass")
    # Rear engine deck: dark recessed grills and separated steel louvers.
    for x in (-8.6,8.6):
        box(mesh,(x,20.35,-27.0),(13.8,0.4,13.0),"black")
        for z in np.linspace(-32.5,-21.5,13):
            box(mesh,(x,20.75,z),(13.1,0.42,0.42),"darkolive")
        for z in (-34.3,-19.5):
            box(mesh,(x,20.65,z),(14.8,0.6,0.7),"olive")
    tube(mesh,[(-15,14,-39),(-12,10.5,-39.2),(0,9.3,-39.8),
               (12,10.5,-39.2),(15,14,-39)],0.28,"steel")
    # Twin external fuel drums, each with bands, end rim and filler cap.
    for x in (-10.4,10.4):
        z,y=-39.8,23.3
        box(mesh,(x,19.8,z),(15.3,1.0,6.4),"darkolive")
        cylinder(mesh,(x-7.1,y,z),(x+7.1,y,z),4.5,"olive",24)
        for dx in (-6.6,-3.9,3.9,6.6):
            cylinder(mesh,(x+dx-0.18,y,z),(x+dx+0.18,y,z),4.59,"steel",24,caps=False)
        for side in (-1,1):
            annulus(mesh,(x+side*7.15,y,z),(side,0,0),4.45,4.05,"edge",24)
            cylinder(mesh,(x+side*7.17,y,z),(x+side*7.23,y,z),3.94,"olive",24)
            box(mesh,(x+side*7.28,y,z),(0.13,6.2,0.28),"darkolive")
            box(mesh,(x+side*7.28,y,z),(0.13,0.28,6.2),"darkolive")
        cylinder(mesh,(x,27.6,z),(x,28.1,z),0.65,"steel",10)
    return mesh


def make_turret():
    origin=vec((0,21.0,3.0))
    mesh=Mesh("turret",origin)
    cylinder(mesh,(0,-0.45,0),(0,1.2,0),12.5,"darkolive",32)
    loft(mesh,[(1.1,outline(14.5,-16,15,4)),(4,outline(16,-15,16,4)),
               (10.4,outline(13,-12,10,3)),(11.3,outline(12.6,-11.8,9.6,3))])
    for side in (-1,1):
        # Deep, sloping cheek modules are the main 99A silhouette feature.
        vertices=[(4.1,2.1,5.3),(16.6,2.1,3.8),(18.0,3.5,14.2),(6.2,3.5,22.8),
                  (4.2,10.8,3.8),(14.9,10.1,2.8),(15.7,9.2,10.8),(5.0,10.3,15.7)]
        vertices=[vec((x*side,y,z)) for x,y,z in vertices]
        mesh.solid(vertices,BOX_FACES,"darkolive")
        outer=[vertices[i] for i in (1,2,6,5)]
        badge_normal=polygon_normal(outer)
        if badge_normal[0]*side < 0:
            badge_normal=-badge_normal
        badge=(outer[0]*0.2+outer[1]*0.8+outer[3]*0.2+outer[2]*0.8)*0.5+badge_normal*0.18
        across=unit(outer[1]-outer[0])*1.75
        up=unit(np.cross(badge_normal,across))
        if up[1] < 0:
            up=-up
        up*=1.75
        decal(mesh,[badge-across-up,badge+across-up,badge+across+up,badge-across+up],"star",badge_normal)
        front=[vertices[3],vertices[2],vertices[6],vertices[7]]
        if polygon_normal(front)[2] < 0:
            front.reverse()
        panel_grid(mesh,front,2,3,0.55)
        roof=[vertices[4],vertices[5],vertices[6],vertices[7]]
        if polygon_normal(roof)[1] < 0:
            roof.reverse()
        panel_grid(mesh,roof,2,3,0.38)
        for z in (-10.6,-5.2,0.2):
            bevel_box(mesh,(side*15.0,6.0,z),(2.0,7.8,5.05),0.25)
        # Numbers sit on the flat rear side armor, away from moving mantlet.
        x=side*16.04
        points=[(x,3.4,1.8),(x,3.4,-12.8),(x,8.4,-12.8),(x,8.4,1.8)]
        if side < 0:
            points=[points[1],points[0],points[3],points[2]]
        decal(mesh,points,"number",(side,0,0))
        # Six smoke dischargers, inclined out and forwards.
        for row in range(2):
            for col in range(3):
                start=vec((side*(16.0+row*0.5),5.0+row*1.4,4.0+col*1.5))
                axis=unit((side*0.8,0.36,0.7))
                end=start+axis*2.6
                cylinder(mesh,start,end,0.56,"steel",12)
                annulus(mesh,end+axis*0.05,axis,0.60,0.39,"edge",12)
                cylinder(mesh,end-axis*0.12,end,0.37,"bore",12)
        cylinder(mesh,(side*10.5,11.0,-10),(side*10.5,12.6,-10),0.55,"darkolive",12)
        cylinder(mesh,(side*10.5,12.6,-10),(side*10.5,27 if side>0 else 24,-10.4),0.11,"steel",8,end_radius=0.065)
    # Mantlet, coax aperture and flexible-looking barrel collar.
    bevel_box(mesh,(0,7.6,13.0),(8.9,5.9,5.0),0.7,"darkolive")
    cylinder(mesh,(0,8.4,14.0),(0,8.4,16.0),2.2,"olive",20)
    cylinder(mesh,(-3.3,7.0,15.0),(-3.3,7.0,18.0),0.38,"black",10)
    # Rear bustle boxes and two small team-color identification plates.
    for x in (-9.5,0,9.5):
        bevel_box(mesh,(x,6.3,-15.4),(9.1,7.0,5.2),0.4)
    for x in (-11,11):
        box(mesh,(x,7.5,-18.10),(3.8,2.8,0.08),"team")
    # Rear basket: see-through bars rather than a solid cuboid.
    for x in (-13.0,-6.5,0,6.5,13.0):
        tube(mesh,[(x,9.6,-12.7),(x,9.6,-20.5),(x,15.0,-20.5)],0.18,"darkolive")
    for y in (9.7,12.0,15.0):
        tube(mesh,[(-13,y,-12.7),(-13,y,-20.5),(13,y,-20.5),(13,y,-12.7)],0.20,"steel")
    for z in (-14,-16,-18,-20):
        cylinder(mesh,(-13,9.6,z),(13,9.6,z),0.12,"darkolive",6)
    cylinder(mesh,(-5,11.6,-17),(5,11.6,-17),1.8,"canvas",12)
    for x in (-3.5,3.5):
        cylinder(mesh,(x-0.15,11.6,-17),(x+0.15,11.6,-17),1.86,"darkolive",12,caps=False)
    # Commander's cupola, optical blocks, and open hatch.
    for x,z in ((6.4,-2.6),(-6.4,-1.7)):
        cylinder(mesh,(x,11.1,z),(x,12.35,z),3.75,"darkolive",24)
        cylinder(mesh,(x,12.35,z),(x,12.8,z),3.48,"olive",24)
        for i in range(8):
            angle=i*TAU/8
            p=(x+3.0*math.cos(angle),12.6,z+3.0*math.sin(angle))
            box(mesh,p,(1.0,0.75,0.7),"glassdark")
    hatch_center=vec((6.4,16.3,-5.2))
    hatch_axis=unit((0,0.32,0.95))
    cylinder(mesh,hatch_center-hatch_axis*0.28,hatch_center+hatch_axis*0.28,3.35,"olive",24)
    annulus(mesh,hatch_center+hatch_axis*0.30,hatch_axis,3.20,2.93,"edge",24)
    tube(mesh,[(5.2,16.0,-4.5),(5.2,17.1,-4.5),(7.5,17.1,-4.5),(7.5,16.0,-4.5)],0.13,"darkolive")
    tube(mesh,[(-7.6,12.95,-1.7),(-7.6,13.65,-1.7),(-5.4,13.65,-1.7),(-5.4,12.95,-1.7)],0.15,"steel")
    # Gunner's sight, panoramic sight and warning sensor.
    bevel_box(mesh,(-8.1,13.1,6.4),(4.5,3.3,4.2),0.3,"olive")
    box(mesh,(-8.1,13.2,8.55),(3.1,1.6,0.14),"glassdark")
    box(mesh,(-8.1,13.3,8.65),(2.1,0.95,0.06),"glass")
    cylinder(mesh,(8.6,11.3,5.0),(8.6,15.5,5.0),1.15,"darkolive",16)
    bevel_box(mesh,(8.6,16.0,5.0),(3.4,3.0,3.1),0.35,"olive")
    box(mesh,(8.6,16.2,6.61),(2.2,1.2,0.08),"glass")
    bevel_box(mesh,(-11,13.2,-7.0),(2.6,3.0,2.8),0.25,"darkolive")
    box(mesh,(-11,13.5,-5.55),(1.8,1.3,0.08),"glassdark")
    # Roof-mounted visual machine gun and ammunition box (not a new weapon slot).
    cylinder(mesh,(-6.4,12.5,0.4),(-6.4,16.1,0.4),0.82,"steel",12)
    bevel_box(mesh,(-6.4,17.2,1.4),(2.0,1.65,5.8),0.20,"black")
    cylinder(mesh,(-6.4,17.55,4.3),(-6.4,17.55,13.4),0.26,"steel",12)
    cylinder(mesh,(-6.4,17.55,12.7),(-6.4,17.55,13.8),0.38,"black",12)
    box(mesh,(-6.4,17.8,-2.9),(1.0,0.8,2.3),"darkolive")
    bevel_box(mesh,(-8.3,16.8,1.4),(2.8,2.8,3.3),0.15,"olive")
    tube(mesh,[(-6.6,18.1,7.3),(-6.6,19.0,7.3),(-6.0,19.0,7.3),(-6.0,18.1,7.3)],0.095,"steel",6)
    return mesh


def make_gun():
    mesh=Mesh("gun",vec((0,29.4,16.0)))
    sections=[(0,4,1.7),(4,17.5,1.03),(17.5,23,1.12),
              (23,28.5,1.57),(28.5,41.0,1.02),(41,59.5,0.91)]
    for start,end,radius in sections:
        cylinder(mesh,(0,0,start),(0,0,end),radius,"camo",20)
    for z,r in ((4,1.23),(10,1.17),(17.5,1.28),(22.9,1.65),(28.5,1.62),(35.0,1.17),(41.0,1.13),(55.0,1.03)):
        cylinder(mesh,(0,0,z-0.16),(0,0,z+0.16),r,"darkolive",20)
        annulus(mesh,(0,0,z+0.17),(0,0,1),r,r-0.09,"edge",20)
    # Open muzzle: dark recessed bore behind an annular end face.
    cylinder(mesh,(0,0,59.5),(0,0,62.5),0.92,"steel",24,caps=False)
    cylinder(mesh,(0,0,59.5),(0,0,62.5),0.69,"bore",24,caps=False)
    cylinder(mesh,(0,0,61.8),(0,0,61.9),0.70,"bore",24)
    annulus(mesh,(0,0,62.5),(0,0,1),0.92,0.69,"edge",24)
    bevel_box(mesh,(0,1.08,55.2),(1.1,0.9,1.5),0.10,"darkolive")
    box(mesh,(0,1.12,56.0),(0.65,0.38,0.04),"glassdark")
    return mesh


@dataclass
class Piece:
    name: str
    offset: tuple
    mesh: Mesh | None = None
    children: list = field(default_factory=list)


def make_model(track_data=None):
    track_data = make_track_data() if track_data is None else track_data
    wheel=make_wheel()
    flare=Piece("Flare",(0,0,62.5))
    gun=Piece("Gun",(0,8.4,13.0),make_gun(),[flare])
    turret=Piece("Turret",(0,21.0,3.0),make_turret(),[gun])
    root=Piece("Base",(0,0,0),make_hull(),[turret])
    for side,label in ((-1,"L"),(1,"R")):
        for i,z in enumerate(WHEEL_Z,1):
            root.children.append(Piece(f"Wheel{label}{i}",(side*track_data["halfWidth"],6.15,z),wheel))
    root.children.extend(make_tracks(track_data))
    return root


def walk(piece, origin=None):
    origin=np.zeros(3) if origin is None else origin
    position=origin+piece.offset
    yield piece,position
    for child in piece.children:
        yield from walk(child,position)


def model_bounds(root):
    points=np.concatenate([np.asarray(p.mesh.positions)+offset for p,offset in walk(root) if p.mesh])
    return points.min(axis=0),points.max(axis=0)


def write_s3o(root, path, textures=("ztz99a_diffuse.tga", "ztz99a_material.tga")):
    data=bytearray(52)
    def append(blob):
        data.extend(b"\0"*((-len(data)) % 4))
        offset=len(data)
        data.extend(blob)
        return offset
    def piece_offset(piece):
        offset=append(bytes(52))
        name=append(piece.name.encode()+b"\0")
        mesh=piece.mesh
        count=len(mesh.positions) if mesh else 0
        vertices=indices=0
        if mesh:
            array=np.column_stack((mesh.positions,mesh.normals,mesh.uvs)).astype("<f4")
            # The native S3O texture loader uses top-origin V coordinates.
            array[:,7]=1-array[:,7]
            vertices=append(array.tobytes())
            indices=append(np.asarray(mesh.indices,dtype="<i4").tobytes())
        children=[piece_offset(child) for child in piece.children]
        child_table=append(struct.pack("<"+"i"*len(children),*children)) if children else 0
        struct.pack_into("<10i3f",data,offset,name,len(children),child_table,count,vertices,
                         0,0,len(mesh.indices) if mesh else 0,indices,0,*piece.offset)
        return offset
    root_offset=piece_offset(root)
    tex1=append(textures[0].encode("utf-8")+b"\0")
    tex2=append(textures[1].encode("utf-8")+b"\0")
    low,high=model_bounds(root)
    middle=vec((0,18,0))
    radius=max(np.linalg.norm(vec(corner)-middle) for corner in (low,high))
    struct.pack_into("<12si5f4i",data,0,b"Spring unit\0",0,radius,float(high[1]),*middle,
                     root_offset,0,tex1,tex2)
    path.write_bytes(data)


def write_glb(root, atlas, extra, path, generator="MyGame procedural ZTZ-99A"):
    binary=bytearray()
    document={"asset":{"version":"2.0","generator":generator},
              "scene":0,"scenes":[{"nodes":[0]}],"nodes":[],"meshes":[],
              "accessors":[],"bufferViews":[],"buffers":[],
              "materials":[{"name":"painted_armor","pbrMetallicRoughness":{
                  "baseColorTexture":{"index":0},"metallicFactor":0.15,"roughnessFactor":0.76},
                  "doubleSided":False,"alphaMode":"MASK","alphaCutoff":0.5}],
              "textures":[{"sampler":0,"source":0}],
              "samplers":[{"magFilter":9729,"minFilter":9987,"wrapS":33071,"wrapT":33071}]}
    def buffer_view(blob,target=None):
        binary.extend(b"\0"*((-len(binary)) % 4))
        offset=len(binary)
        binary.extend(blob)
        entry={"buffer":0,"byteOffset":offset,"byteLength":len(blob)}
        if target:
            entry["target"]=target
        document["bufferViews"].append(entry)
        return len(document["bufferViews"])-1
    def accessor(array,component,kind,target):
        array=np.asarray(array,dtype="<f4" if component==5126 else "<u4")
        entry={"bufferView":buffer_view(array.tobytes(),target),"componentType":component,
               "count":len(array),"type":kind}
        if kind=="VEC3":
            entry.update(min=array.min(axis=0).tolist(),max=array.max(axis=0).tolist())
        document["accessors"].append(entry)
        return len(document["accessors"])-1
    mesh_ids={}
    def add(piece):
        index=len(document["nodes"])
        node={"name":piece.name,"translation":list(piece.offset)}
        document["nodes"].append(node)
        if piece.mesh:
            mesh=piece.mesh
            if mesh.name not in mesh_ids:
                uv=np.asarray(mesh.uvs).copy()
                uv[:,1]=1-uv[:,1]
                attributes={"POSITION":accessor(mesh.positions,5126,"VEC3",34962),
                            "NORMAL":accessor(mesh.normals,5126,"VEC3",34962),
                            "TEXCOORD_0":accessor(uv,5126,"VEC2",34962)}
                primitive={"attributes":attributes,"indices":accessor(mesh.indices,5125,"SCALAR",34963),
                           "material":0,"mode":4}
                mesh_ids[mesh.name]=len(document["meshes"])
                document["meshes"].append({"name":mesh.name,"primitives":[primitive]})
            node["mesh"]=mesh_ids[mesh.name]
        if piece.children:
            node["children"]=[add(child) for child in piece.children]
        return index
    add(root)
    png=io.BytesIO()
    exchange_texture=atlas.copy()
    exchange_texture.putalpha(extra.getchannel("A"))
    exchange_texture.save(png,format="PNG")
    document["images"]=[{"bufferView":buffer_view(png.getvalue()),"mimeType":"image/png"}]
    document["buffers"]=[{"byteLength":len(binary)}]
    encoded=json.dumps(document,separators=(",",":")).encode()
    encoded+=b" "*((-len(encoded)) % 4)
    binary.extend(b"\0"*((-len(binary)) % 4))
    total=12+8+len(encoded)+8+len(binary)
    path.write_bytes(struct.pack("<III",0x46546C67,2,total)+struct.pack("<II",len(encoded),0x4E4F534A)+
                     encoded+struct.pack("<II",len(binary),0x004E4942)+binary)


def assembled(root):
    vertices,normals,uvs,indices=[],[],[],[]
    for piece,offset in walk(root):
        if not piece.mesh:
            continue
        mesh=piece.mesh
        indices.extend(np.asarray(mesh.indices).reshape(-1,3)+len(vertices))
        vertices.extend(np.asarray(mesh.positions)+offset)
        normals.extend(mesh.normals)
        uvs.extend(mesh.uvs)
    return np.asarray(vertices),np.asarray(normals),np.asarray(uvs),np.asarray(indices)


def render(root,atlas,extra,path,eye=(125,95,155),width=1500,height=1000,transparent=False,
           target=(0,16,7)):
    vertices,normals,uvs,triangles=assembled(root)
    eye=vec(eye)
    forward=unit(vec(target)-eye)
    camera_up=(0,0,-1) if abs(forward[1])>0.999 else (0,1,0)
    right=unit(np.cross(forward,camera_up))
    up=unit(np.cross(right,forward))
    rotation=np.stack((right,up,forward),axis=1)
    projected=vertices @ rotation
    low,high=projected[:,:2].min(axis=0),projected[:,:2].max(axis=0)
    scale=min(width*0.87/(high[0]-low[0]),height*0.80/(high[1]-low[1]))
    center=(low+high)/2
    def project(points):
        q=np.asarray(points) @ rotation
        return np.column_stack(((q[:,0]-center[0])*scale+width/2,
                                height*0.46-(q[:,1]-center[1])*scale,q[:,2]))
    screen=project(vertices)
    background=(226,230,221,0 if transparent else 255)
    image=Image.new("RGBA",(width,height),background)
    if not transparent:
        shadow=Image.new("RGBA",image.size)
        draw=ImageDraw.Draw(shadow)
        light=unit((-0.65,1.3,0.7))
        cast=vertices.copy()
        cast[:,0]-=(vertices[:,1]+0.5)*light[0]/light[1]
        cast[:,2]-=(vertices[:,1]+0.5)*light[2]/light[1]
        cast[:,1]=-0.5
        s=project(cast)
        for triangle in triangles:
            draw.polygon([tuple(p) for p in s[triangle,:2]],fill=(24,38,30,47))
        shadow=shadow.filter(ImageFilter.GaussianBlur(9))
        image=Image.alpha_composite(image,shadow)
    pixels=np.asarray(image).copy()
    depth=np.full((height,width),np.inf,dtype=np.float32)
    tex=np.asarray(atlas)
    visibility=np.asarray(extra.getchannel("A"))
    light=unit((-0.6,1.0,0.8))
    fill=unit((0.7,0.3,-0.5))
    for triangle in triangles:
        p=screen[triangle]
        world=vertices[triangle]
        if np.dot(np.cross(world[1]-world[0],world[2]-world[0]),-forward) <= 0:
            continue
        x0=max(0,int(np.floor(p[:,0].min())))
        x1=min(width-1,int(np.ceil(p[:,0].max())))
        y0=max(0,int(np.floor(p[:,1].min())))
        y1=min(height-1,int(np.ceil(p[:,1].max())))
        if x0>x1 or y0>y1:
            continue
        denom=(p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
        if abs(denom)<1e-8:
            continue
        yy,xx=np.mgrid[y0:y1+1,x0:x1+1]
        a=((p[1,1]-p[2,1])*(xx+0.5-p[2,0])+(p[2,0]-p[1,0])*(yy+0.5-p[2,1]))/denom
        b=((p[2,1]-p[0,1])*(xx+0.5-p[2,0])+(p[0,0]-p[2,0])*(yy+0.5-p[2,1]))/denom
        c=1-a-b
        z=a*p[0,2]+b*p[1,2]+c*p[2,2]
        mask=(a>=-1e-6)&(b>=-1e-6)&(c>=-1e-6)&(z<depth[y0:y1+1,x0:x1+1])
        if not mask.any():
            continue
        weights=np.stack((a[mask],b[mask],c[mask]),axis=1)
        n=weights @ normals[triangle]
        n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-9)
        uv=weights @ uvs[triangle]
        tx=np.clip((uv[:,0]*tex.shape[1]).astype(int),0,tex.shape[1]-1)
        ty=np.clip(((1-uv[:,1])*tex.shape[0]).astype(int),0,tex.shape[0]-1)
        visible=visibility[ty,tx]>=128
        mask[mask]=visible
        if not visible.any():
            continue
        n,tx,ty=n[visible],tx[visible],ty[visible]
        color=tex[ty,tx,:3].astype(float)
        alpha=tex[ty,tx,3:4]/255
        color=color*(1-alpha)+vec(COLORS["team"])*alpha
        diffuse=0.38+0.66*np.maximum(n @ light,0)+0.16*np.maximum(n @ fill,0)
        color=np.clip(color*diffuse[:,None],0,255)
        target=pixels[y0:y1+1,x0:x1+1]
        target[mask,:3]=color.astype(np.uint8)
        target[mask,3]=255
        depth[y0:y1+1,x0:x1+1][mask]=z[mask]
    image=Image.fromarray(pixels)
    image.save(path)
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-preview",action="store_true")
    args=parser.parse_args()
    atlas,extra=make_atlas()
    track_data=make_track_data()
    model=make_model(track_data)
    objects,textures=ROOT/"Objects3d",ROOT/"UnitTextures"
    previews=ROOT/"tools"/"previews"
    for directory in (objects,textures,previews,ROOT/"UnitPics",ROOT/"Scripts"):
        directory.mkdir(parents=True,exist_ok=True)
    atlas.save(textures/"ztz99a_diffuse.tga",compression=None)
    extra.save(textures/"ztz99a_material.tga",compression=None)
    write_s3o(model,objects/"ztz99a.s3o")
    write_glb(model,atlas,extra,objects/"ztz99a.glb")
    write_track_data(track_data,ROOT/"Scripts"/"ztz99a_track_data.lua")
    low,high=model_bounds(model)
    report={"pieces":[p.name for p,_ in walk(model)],
            "triangles":sum(len(p.mesh.indices)//3 for p,_ in walk(model) if p.mesh),
            "bounds":{"min":low.tolist(),"max":high.tolist()},
            "native_model":"Objects3d/ztz99a.s3o","exchange_model":"Objects3d/ztz99a.glb",
            "texture_size":[1024,1024],"coordinates":"X right, Y up, Z forward",
            "old_model_preserved":"Objects3d/MBT.glb",
            "track_data":"Scripts/ztz99a_track_data.lua","track":track_data}
    (previews/"ztz99a_manifest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(f"Built {len(report['pieces'])} pieces / {report['triangles']} triangles",flush=True)
    print(f"Wrote track data for {track_data['linkCount']} links per side",flush=True)
    if not args.no_preview:
        render(model,atlas,extra,previews/"ztz99a_front.png")
        print("Rendered front three-quarter view",flush=True)
        render(model,atlas,extra,previews/"ztz99a_rear.png",eye=(-130,80,-140))
        print("Rendered rear three-quarter view",flush=True)
        render(model,atlas,extra,previews/"ztz99a_side.png",eye=(160,40,5),width=1500,height=820)
        icon=render(model,atlas,extra,previews/"ztz99a_icon_source.png",width=512,height=512,transparent=True)
        icon.resize((256,256),Image.Resampling.LANCZOS).save(ROOT/"UnitPics"/"ztz99a.png")
        print("Rendered side view and build icon",flush=True)


if __name__=="__main__":
    main()
