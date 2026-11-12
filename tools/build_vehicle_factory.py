"""Vehicle Factory: flat-shaded industrial building, native/GLB export and checks.

    python -I -B tools/build_vehicle_factory.py
    python -I -B tools/build_vehicle_factory.py --no-preview
    python -I -B tools/build_vehicle_factory.py --gray --check-only

Default output is the finished industrial palette. --gray generates a neutral
inspection version of the current geometry, not the retained original G1 images.
--no-preview skips studio views but still builds the runtime icon. --check-only
is read-only. Only vehicle_factory-prefixed assets and their preview directory
are written; old assets, UnitDefs, control scripts and the engine are untouched.

M1A1 v1 supplies flat faces, quiet large surfaces and economical functional detail,
not its tank proportions or sand palette. Factory anchors: slotted double portal,
rear pitched workshop, open assembly bay/bridge, asymmetric low service pods,
and a low continuous drive floor. All lengths are Recoil world units, NOT metres.
Rigid motions are a Lua contract; the GLB contains no baked animation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import itertools
import json
import math
import pathlib
import struct
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Keep imports read-only even when this module is imported by another tool.
sys.dont_write_bytecode = True
TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from build_ztz99a import (Mesh as BaseMesh, Piece, annulus, box, cylinder,
                          loft, model_bounds, outline, render, vec, walk,
                          write_glb, write_s3o)
import build_m1a1
import build_spider
import build_scout

PRODUCTS = ("spider", "stumpy", "flare", "duron", "scout", "m1a1")
PREVIEWS = TOOLS / "previews" / "vehicle_factory"
ATLAS_SIZE = 512
TRIANGLE_REVIEW_LIMIT = 6000  # Brief's review ceiling, not an engine/project limit.
# Supplied by the coordinator's read-only native-vertex motion analysis. These
# are conservative independent joint ranges, NOT measured running game poses.
# Pin the measured native inputs; changing a product requires re-measurement.
PRODUCT_PROXY_EVIDENCE = "mygame-factory-baseline-_miw1kgg/debug/product_space_report.json (2026-11-10)"
PRODUCT_MOTION_PROXIES = {
    "spider": dict(horizontalRadiusWorld=38.086350, minYWorld=0.0, maxYWorld=23.786963,
        nativeSha256="a7201d5030427830e385acdadbec6c4f484d2644f25acb16ab5a130f11bde82f",
        jointRanges="hip yaw=rest +/-34 deg; knee Z=0..15 deg; arms -16..0 / forearms 0..14 deg"),
    "stumpy": dict(horizontalRadiusWorld=16.281585, minYWorld=-0.65, maxYWorld=29.182082,
        nativeSha256="726502452d2b9f4155b9bd84a68b0c88d8b5ce9dca31426bc772a546a15ceb25",
        jointRanges="turret full yaw; barrel unrestricted pitch; wheel X rotation"),
    "flare": dict(horizontalRadiusWorld=28.504386, minYWorld=-1.0, maxYWorld=28.367534,
        nativeSha256="0e42545931add93150a9d83e841e5ad5b79bcad5bd0f9cc031ae0d539707f5a6",
        jointRanges="turret full yaw; barrel unrestricted pitch; wheel X rotation"),
    "duron": dict(horizontalRadiusWorld=30.372247, minYWorld=-1.344, maxYWorld=45.136890,
        nativeSha256="bc9e310bc5627b9b81a5f155beecbf11b549b0d173eb516eed66c25a32e111b6",
        jointRanges="turret full yaw; barrel unrestricted pitch"),
}
PROXY_ROUNDING_PAD = 0.001  # Outward padding on the report's six-decimal values.
PIECE_PARENTS = {
    "Base": None, "DoorL": "Base", "DoorR": "Base", "Gantry": "Base",
    "HeadL": "Gantry", "NanoL": "HeadL", "HeadR": "Gantry", "NanoR": "HeadR",
    "FanL": "Base", "FanR": "Base", "WorkLamp": "Base", "BuildSpot": "Base",
}
GRAY = {
    "shell": (168, 168, 168), "shell_light": (194, 194, 194),
    "roof": (118, 118, 118), "structure": (76, 76, 76),
    "floor": (119, 119, 119), "recess": (43, 43, 43),
    "metal": (136, 136, 136), "window": (66, 66, 66),
    "lamp": (208, 208, 208), "team": (166, 166, 166),
    "warning": (162, 162, 162), "panel": (140, 140, 140),
}
COLORS = {
    "shell": (174, 182, 182), "shell_light": (208, 213, 207),
    "roof": (70, 86, 101), "structure": (42, 50, 57),
    "floor": (114, 113, 104), "recess": (25, 32, 37),
    "metal": (117, 129, 132), "window": (57, 98, 114),
    "lamp": (232, 184, 77), "team": (68, 133, 185),
    "warning": (205, 162, 70), "panel": (137, 151, 156),
}
PATTERNS = {"lane": "floor", "door_panel": "roof", "grille": "recess", "badge": "structure"}
TILE = ATLAS_SIZE // 4
RECTS = {name: (8 + i % 4 * TILE, 8 + i // 4 * TILE,
                (i % 4 + 1) * TILE - 9, (i // 4 + 1) * TILE - 9)
         for i, name in enumerate((*GRAY, *PATTERNS))}


@dataclass(frozen=True)
class FactorySpec:
    footprint_x: int = 12
    footprint_z: int = 10
    footprint_cell_world: float = 16.0
    game_square_world: float = 8.0
    foundation_half_x: float = 94.0
    foundation_half_z: float = 78.0
    skirt_bottom_y: float = -3.5
    floor_y: float = 0.12
    lane_half_x: float = 46.0
    rear_inner_z: float = -72.0
    roof_front_z: float = -25.0
    build_z: float = -8.0
    door_z: float = 52.0
    door_travel: float = 48.0
    door_bottom_y: float = 0.5
    door_top_y: float = 52.0
    door_thickness: float = 3.0
    lintel_bottom_y: float = 52.5
    gantry_y: float = 62.0  # Entire bridge/runway lifted 6; tool minimum is 48.
    gantry_z: float = -8.0
    gantry_move_z_min: float = 0.0
    gantry_move_z_max: float = 28.0
    head_x: float = 23.0
    head_move_x_min: float = -4.0
    head_move_x_max: float = 4.0
    head_move_y_min: float = -5.0
    head_move_y_max: float = 0.0
    fan_x: float = 77.0
    fan_y: float = 30.3
    fan_z: tuple = (-34.0, 9.0)


SPEC = FactorySpec()


def atlas_uv(material, u, v):
    x0, y0, x1, y1 = RECTS[material]
    return ((x0 + u * (x1 - x0)) / ATLAS_SIZE,
            1 - (y1 - v * (y1 - y0)) / ATLAS_SIZE)


class Mesh(BaseMesh):
    """Own semantic UVs; never falls back to the legacy camouflage palette."""

    def __init__(self, name):
        super().__init__(name)
        self.components = []

    def face(self, points, material="shell", outward=None, normals=None, uvs=None):
        p = np.asarray(points)
        if uvs is None and material == "floor" and np.all(np.abs(p[:, 1] - SPEC.floor_y) < 1e-8):
            material = "lane"
            uvs = [atlas_uv(material, (v[0]+SPEC.foundation_half_x)/(2*SPEC.foundation_half_x),
                            (SPEC.foundation_half_z-v[2])/(2*SPEC.foundation_half_z)) for v in p]
        elif uvs is None and material == "door_panel":
            if np.ptp(p[:, 2]) < 1e-8:
                uvs = [atlas_uv(material, v[0]/SPEC.lane_half_x+0.5,
                               v[1]/(SPEC.door_top_y-SPEC.door_bottom_y)+0.5) for v in p]
            else:
                material = "roof"
        if uvs is None:
            x0, y0, x1, y1 = RECTS[material]
            uv = ((x0 + x1) / (2 * ATLAS_SIZE), 1 - (y0 + y1) / (2 * ATLAS_SIZE))
            uvs = [uv] * len(points)
        super().face(points, material, outward, normals, uvs)


def component(mesh, name, role, operation):
    """Retain per-solid conservative bounds for reproducible clearance checks."""
    vi, ii = len(mesh.positions), len(mesh.indices)
    operation()
    points = np.asarray(mesh.positions[vi:])
    mesh.components.append(dict(name=name, role=role, vertex_start=vi,
        vertex_count=len(mesh.positions) - vi, index_start=ii,
        index_count=len(mesh.indices) - ii,
        min=points.min(axis=0).tolist(), max=points.max(axis=0).tolist()))


def block(mesh, name, low, high, material="shell", role="fixed_solid"):
    low, high = vec(low), vec(high)
    if not np.all(high > low):
        raise ValueError(f"Non-positive block: {name}")
    component(mesh, name, role,
              lambda: box(mesh, (low + high) / 2, high - low, material))


def prism(mesh, name, section, start, end, axis="z", material="shell", role="fixed_solid", end_material=None):
    """Extrude a CONVEX section; Mesh's fan triangulation is not used on concavity."""
    section = np.asarray(section, dtype=float)
    edges = np.roll(section, -1, axis=0) - section
    turns = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] - \
        edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
    if not (np.all(turns >= -1e-9) or np.all(turns <= 1e-9)):
        raise ValueError(f"Non-convex section: {name}")
    def point(uv, t):
        a, b = uv
        return (a, b, t) if axis == "z" else (t, a, b) if axis == "x" else (a, t, b)
    vertices = [point(uv, t) for t in (start, end) for uv in section]
    n = len(section)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    def make():
        center = np.mean(vertices, axis=0)
        for i, ids in enumerate(faces):
            points = [vertices[j] for j in ids]
            mesh.face(points, end_material if i == 1 and end_material is not None else material,
                      outward=np.mean(points, axis=0)-center)
    component(mesh, name, role, make)


def surface(mesh, name, points, material, outward, role="fixed_surface"):
    component(mesh, name, role, lambda: mesh.face(points, material, outward=outward))


def patterned_surface(mesh, name, points, material, outward):
    if len(points) != 4:
        raise ValueError("Pattern panels require four ordered corners")
    uv = [atlas_uv(material, u, v) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    component(mesh, name, "fixed_surface", lambda: mesh.face(points, material, outward=outward, uvs=uv))


def ring_housing(mesh, name, center, y0, y1, outer=14.0, inner=12.5):
    x, z = center
    def make():
        cylinder(mesh, (x, y0, z), (x, y1, z), outer, "shell_light",
                 segments=12, caps=False, smooth=False)
        for i in range(12):
            a, b = i * math.tau / 12, (i + 1) * math.tau / 12
            p = [(x + inner * math.cos(t), y, z + inner * math.sin(t))
                 for t, y in ((a, y0), (b, y0), (b, y1), (a, y1))]
            mesh.face(p, "recess", outward=(-math.cos((a+b)/2), 0, -math.sin((a+b)/2)))
        annulus(mesh, (x, y1, z), (0, 1, 0), outer, inner, "shell_light", 12)
        annulus(mesh, (x, y0, z), (0, -1, 0), outer, inner, "structure", 12)
    component(mesh, name, "fan_housing", make)


def make_base(s=SPEC):
    m = Mesh("vehicle_factory_base")
    h, dz = s.lane_half_x, s.door_z
    component(m, "foundation_drive_floor", "drive_floor", lambda: loft(m, [
        (s.skirt_bottom_y, outline(s.foundation_half_x, -s.foundation_half_z,
                                  s.foundation_half_z, 6)),
        (s.floor_y, outline(s.foundation_half_x, -s.foundation_half_z,
                           s.foundation_half_z, 6))], "floor"))
    # The entire central lane stays at floor_y. Raised side pads stop BEFORE
    # the door slot, so there is no hidden raised sill through a door pocket.
    for side, label in ((-1, "L"), (1, "R")):
        xa, xb = sorted((side*h, side*s.foundation_half_x))
        # Pull the pad inside the rear wall to avoid coincident outward faces.
        block(m, f"side_pad_{label}", (xa, s.floor_y, -75.9), (xb, 2, dz-8), "structure")
        block(m, f"front_pad_{label}", (xa, s.floor_y, dz+8), (xb, 1.3, 73), "structure")
        xa, xb = sorted((side*h, side*(h+8)))
        block(m, f"rear_side_wall_{label}", (xa, 2, -72), (xb, 55, s.roof_front_z), "shell")
        block(m, f"bay_knee_wall_{label}", (xa, 2, s.roof_front_z), (xb, 24, dz-8.5), "shell")
        for z in (-19, 32):
            block(m, f"runway_pier_{label}_{z}", (xa, 24, z-4),
                  (xb, s.gantry_y-4, z+4), "shell_light")
        xa, xb = sorted((side*(h+1), side*(h+7)))
        block(m, f"bridge_runway_{label}", (xa, s.gantry_y-4, -27),
              (xb, s.gantry_y-1.2, 42), "structure")

    # High rear workshop is a shell, not a box filling the production space.
    prism(m, "rear_gable_wall", [(-55, s.floor_y), (55, s.floor_y),
        (55, 54.55), (14, 61.5), (-14, 61.5), (-55, 54.55)], -76, -72,
        end_material="structure")  # Inward face, not a fake plane across the doorway.
    prism(m, "roof_left_slope", [(-58, 53.5), (-14, 61.5), (-14, 64), (-58, 56)],
          -77, s.roof_front_z, material="roof")
    prism(m, "roof_right_slope", [(14, 61.5), (58, 53.5), (58, 56), (14, 64)],
          -77, s.roof_front_z, material="roof")
    block(m, "roof_ridge", (-14, 61.5, -77), (14, 64, s.roof_front_z), "roof")
    block(m, "workshop_front_tie", (-h, 52.5, -29), (h, 55, -25), "structure")

    # Raked-front control cabin. Only one wide window surface as a scale cue.
    prism(m, "control_cabin", [(3, -60), (3, 26), (17, 30), (26, 25), (29, -60)],
          -90, -56, axis="x", material="shell")
    surface(m, "control_window", [(-85, 19, 28.99), (-61, 19, 28.99),
        (-61, 24.5, 25.934), (-85, 24.5, 25.934)], "window", (0, 5, 9))
    block(m, "control_rear_supply", (-88, 2, -73), (-58, 20, -60), "roof")

    # Lower cooling pod has real 12-sided circular openings around two fans.
    prism(m, "cooling_pod", [(56, 2), (92, 2), (92, 24), (87, 29), (60, 29), (56, 25)],
          -70, 27, material="shell")
    for label, z in zip(("L", "R"), s.fan_z):
        ring_housing(m, f"cooling_ring_{label}", (s.fan_x, z), 29, 32)
        surface(m, f"fan_well_{label}", [(s.fan_x+12.5*math.cos(i*math.tau/12),
            29.01, z+12.5*math.sin(i*math.tau/12)) for i in range(12)], "recess", (0, 1, 0))
    # One broad hollow flue is a functional silhouette anchor, not roof clutter.
    block(m, "flue_front", (68, 29, -56), (86, 80, -53), "roof")
    block(m, "flue_rear", (68, 29, -71), (86, 80, -68), "roof")
    block(m, "flue_left", (68, 29, -68), (71, 80, -56), "shell")
    block(m, "flue_right", (83, 29, -68), (86, 80, -56), "shell")
    block(m, "flue_dark_well", (71, 74, -68), (83, 74.3, -56), "recess")

    # Continuous real slots. No post at x=+/-h occupies z=dz+/-2.25.
    # Leaf open outer edge is h+travel; the cavity end has a further 1 unit gap.
    end = h + s.door_travel + 1
    for side, label in ((-1, "L"), (1, "R")):
        xa, xb = sorted((side*h, side*(end+1)))
        block(m, f"pocket_{label}_front_skin", (xa, s.floor_y, dz+2.25),
              (xb, s.lintel_bottom_y, dz+7), "shell_light")
        block(m, f"pocket_{label}_rear_skin", (xa, s.floor_y, dz-7),
              (xb, s.lintel_bottom_y, dz-2.25), "shell")
        ca, cb = sorted((side*end, side*(end+1)))
        block(m, f"pocket_{label}_end_cap", (ca, s.floor_y, dz-2.25),
              (cb, s.lintel_bottom_y, dz+2.25), "structure")
        block(m, f"pocket_{label}_top_cap", (xa, s.lintel_bottom_y, dz-7),
              (xb, 60, dz+7), "roof")
    prism(m, "portal_header", [(-h, s.lintel_bottom_y), (h, s.lintel_bottom_y),
        (h, 60), (h-9, 63), (-h+9, 63), (-h, 60)], dz-7, dz+7, material="shell_light")
    # A single separately movable lamp surface; no second coincident light quad.
    block(m, "lamp_housing", (-6, 55.8, dz+6.5), (6, 60.2, dz+7.2), "structure")
    add_finish_details(m, s)
    return m


def add_finish_details(m, s=SPEC):
    # A few large factory-specific features, all outside the departure volume.
    for side, label in ((-1, "L"), (1, "R")):
        section = np.asarray(((-46, 57.8), (-22, 62.1), (-22, 68.5), (-40, 68.5), (-46, 64)))
        if side > 0:
            section[:, 0] *= -1
        prism(m, f"roof_monitor_{label}", section, -67, -49, material="panel")
        xa, xb = sorted((side*26, side*39))
        surface(m, f"monitor_glass_{label}", [(xa, 64, -48.96), (xb, 64, -48.96),
                (xb, 67, -48.96), (xa, 67, -48.96)], "window", (0, 0, 1))
        xa, xb = sorted((side*4, side*11))
        surface(m, f"roof_team_{label}", [(xa, 64.04, -29), (xb, 64.04, -29),
                (xb, 64.04, -71), (xa, 64.04, -71)], "team", (0, 1, 0))
        component(m, f"apron_bollard_{label}", "fixed_solid", lambda side=side: cylinder(m,
            (side*55, 1.3, 69), (side*55, 10.5, 69), 2.0, "warning", segments=8, smooth=False))
        component(m, f"bollard_band_{label}", "fixed_solid", lambda side=side: cylinder(m,
            (side*55, 7.1, 69), (side*55, 8.7, 69), 2.04, "structure", segments=8, smooth=False))

    surface(m, "portal_team_band", [(-30, 63.04, 50.7), (30, 63.04, 50.7),
            (30, 63.04, 47.8), (-30, 63.04, 47.8)], "team", (0, 1, 0))
    surface(m, "control_side_glass", [(-90.04, 17, -47), (-90.04, 17, 11),
            (-90.04, 24, 11), (-90.04, 24, -47)], "window", (-1, 0, 0))
    for z in (-29, -10):
        block(m, f"control_window_mullion_{z}", (-90.12, 17, z-.55), (-89.7, 24, z+.55), "structure")
    z = s.door_z+7.04
    surface(m, "crew_access_door", [(-79, 1.5, z), (-63, 1.5, z),
            (-63, 24, z), (-79, 24, z)], "structure", (0, 0, 1))
    for x in (-79, -63):
        block(m, f"crew_door_jamb_{x}", (x-.65, 1.3, z), (x+.65, 24.5, z+.35), "panel")
    block(m, "crew_door_header", (-79.65, 24, z), (-62.35, 25, z+.35), "panel")
    surface(m, "crew_door_window", [(-77, 15, z+.04), (-65, 15, z+.04),
            (-65, 21, z+.04), (-77, 21, z+.04)], "window", (0, 0, 1))
    patterned_surface(m, "factory_identification", [(-88, 30, z), (-54, 30, z),
            (-54, 48, z), (-88, 48, z)], "badge", (0, 0, 1))
    patterned_surface(m, "service_vent_front", [(58, 15, z), (86, 15, z),
            (86, 33, z), (58, 33, z)], "grille", (0, 0, 1))
    patterned_surface(m, "service_vent_back", [(-59, 4, -73.04), (-87, 4, -73.04),
            (-87, 18, -73.04), (-59, 18, -73.04)], "grille", (0, 0, -1))
    patterned_surface(m, "cooling_intake_side", [(92.04, 7, 20), (92.04, 7, -42),
            (92.04, 20, -42), (92.04, 20, 20)], "grille", (1, 0, 0))
    route = ((93.1, 23, 19), (93.1, 23, -48), (93.1, 35, -61), (85.5, 35, -61))
    for i, (start, end) in enumerate(zip(route, route[1:])):
        component(m, f"cooling_conduit_{i}", "fixed_solid", lambda start=start, end=end: cylinder(m,
            start, end, 1.35, "metal", segments=8, smooth=False))


def make_door(name, s=SPEC):
    m = Mesh(name)
    w, hh, t = s.lane_half_x / 2, (s.door_top_y-s.door_bottom_y) / 2, s.door_thickness / 2
    # One chamfer band gives the massive slab a legible meeting seam and depth.
    def shape():
        rings = []
        for z, inset in ((-t, 0.7), (-t+0.7, 0), (t-0.7, 0), (t, 0.7)):
            x, y = w-inset, hh-inset
            rings.append([(px, py, z) for px, py in
                          ((-x+1.2, -y), (x-1.2, -y), (x, -y+1.2), (x, y-1.2),
                           (x-1.2, y), (-x+1.2, y), (-x, y-1.2), (-x, -y+1.2))])
        vertices = sum(rings, [])
        faces = [tuple(range(7, -1, -1)), tuple(range(24, 32))]
        faces += [(k*8+i, k*8+(i+1)%8, (k+1)*8+(i+1)%8, (k+1)*8+i)
                  for k in range(3) for i in range(8)]
        m.solid(vertices, faces, "door_panel")
    component(m, "door_leaf", "moving_door", shape)
    return m


def make_gantry():
    m = Mesh("vehicle_factory_gantry")
    block(m, "bridge_beam", (-49.5, -0.5, -5), (49.5, 4.5, 5), "structure", "moving_gantry")
    block(m, "bridge_top_flange", (-49.5, 4.5, -6), (49.5, 5.8, 6), "metal", "moving_gantry")
    surface(m, "bridge_warning_band", [(-36, 0.8, 5.04), (36, 0.8, 5.04),
            (36, 2.5, 5.04), (-36, 2.5, 5.04)], "warning", (0, 0, 1), "moving_gantry")
    for side, label in ((-1, "L"), (1, "R")):
        cx = side*50
        block(m, f"bogie_{label}", (cx-3, -1.2, -7), (cx+3, 2, 7), "roof", "moving_gantry")
    return m


def make_head(name):
    m = Mesh(name)
    block(m, "head_carriage", (-4, -2, -4), (4, 1, 4), "warning", "moving_head")
    # Sliding guide stays engaged with the bridge even at maximum downward
    # travel. Without this shank the entire head would visibly float 4.5 below
    # the beam. The portion inside the beam is an intentional telescopic joint.
    component(m, "head_guide_shank", "telescopic_engagement", lambda: cylinder(m,
        (0, .5, 0), (0, 6.6, 0), 1.3, "metal", segments=8, smooth=False))
    component(m, "head_ram", "moving_head", lambda: cylinder(m, (0, -1.8, 0),
        (0, -6.5, 0), 2.8, "structure", segments=8, end_radius=2.2, smooth=False))
    component(m, "head_tool", "moving_head", lambda: cylinder(m, (0, -6.5, 0),
        (0, -8, 0), 2.2, "metal", segments=8, end_radius=1.3, smooth=False))
    return m


def make_fan(name):
    m = Mesh(name)
    component(m, "fan_hub", "moving_fan", lambda: cylinder(m, (0, -0.3, 0),
        (0, 0.8, 0), 2.2, "metal", segments=8, smooth=False))
    blade = np.asarray(((1.4, -1.2), (9, -3), (11, -0.5), (3, 1.4)))
    for i in range(4):
        angle = i*math.pi/2
        matrix = np.asarray(((math.cos(angle), -math.sin(angle)),
                             (math.sin(angle), math.cos(angle))))
        prism(m, f"fan_blade_{i}", blade @ matrix.T, -0.35, 0.35, axis="y",
              material="structure", role="moving_fan")
    return m


def make_model(s=SPEC):
    root = Piece("Base", (0, 0, 0), make_base(s))
    for side, label in ((-1, "L"), (1, "R")):
        root.children.append(Piece(f"Door{label}",
            (side*s.lane_half_x/2, (s.door_bottom_y+s.door_top_y)/2, s.door_z),
            make_door(f"vehicle_factory_door_{label}", s)))
    gantry = Piece("Gantry", (0, s.gantry_y, s.gantry_z), make_gantry())
    for side, label in ((-1, "L"), (1, "R")):
        gantry.children.append(Piece(f"Head{label}", (side*s.head_x, -1, 0),
            make_head(f"vehicle_factory_head_{label}"), [Piece(f"Nano{label}", (0, -8, 0), None)]))
    root.children.append(gantry)
    for label, z in zip(("L", "R"), s.fan_z):
        root.children.append(Piece(f"Fan{label}", (s.fan_x, s.fan_y, z), make_fan(f"vehicle_factory_fan_{label}")))
    lamp = Mesh("vehicle_factory_work_lamp")
    surface(lamp, "lamp_face", [(-4.4, -1.25, 0), (4.4, -1.25, 0),
        (4.4, 1.25, 0), (-4.4, 1.25, 0)], "lamp", (0, 0, 1), "lamp_surface")
    root.children += [Piece("WorkLamp", (0, 58, s.door_z+7.25), lamp),
                      Piece("BuildSpot", (0, s.floor_y, s.build_z), None)]
    return root


def make_atlas(gray=False):
    palette = GRAY if gray else COLORS
    diffuse = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), palette["shell"]+(0,))
    extra = Image.new("RGBA", diffuse.size, (0, 10, 0, 255))
    paint, material = ImageDraw.Draw(diffuse), ImageDraw.Draw(extra)
    for name in RECTS:
        base = PATTERNS.get(name, name)
        x0, y0, x1, y1 = RECTS[name]
        rect = (x0-8, y0-8, x1+8, y1+8)
        paint.rectangle(rect, fill=palette[base]+(255 if name == "team" and not gray else 0,))
        reflection = 28 if base == "window" else 22 if base == "metal" else 6 if base == "recess" else 10
        material.rectangle(rect, fill=(0, reflection, 0, 255))
    if gray:
        return diffuse, extra

    def patch(name):
        x0, y0, x1, y1 = RECTS[name]
        image = Image.new("RGBA", (x1-x0+1, y1-y0+1), palette[PATTERNS[name]]+(0,))
        return image, ImageDraw.Draw(image), (x0, y0)

    image, draw, pos = patch("lane")
    w, h = image.size
    def floor_point(x, z):
        return ((x+SPEC.foundation_half_x)/(2*SPEC.foundation_half_x)*(w-1),
                (z+SPEC.foundation_half_z)/(2*SPEC.foundation_half_z)*(h-1))
    a, b = floor_point(-35, -38), floor_point(35, 22)
    draw.rectangle((*a, *b), fill=(91, 103, 107, 0), outline=palette["warning"]+(0,), width=2)
    for x in (-42, 42):
        draw.line((floor_point(x, 29), floor_point(x, 72)), fill=palette["shell_light"]+(0,), width=2)
    for z in (43, 54, 65):
        a, b = floor_point(-10, z), floor_point(10, z+3)
        draw.rectangle((*a, *b), fill=palette["warning"]+(0,))
    diffuse.paste(image, pos)

    image, draw, pos = patch("door_panel")
    w, h = image.size
    draw.rectangle((2, 2, w-3, h-3), outline=palette["panel"]+(0,), width=3)
    for y in (20, 44, 68, 92):
        draw.rectangle((5, y-3, w-6, y+1), fill=palette["panel"]+(0,))
        draw.line((5, y+2, w-6, y+2), fill=palette["structure"]+(0,), width=2)
    draw.rectangle((4, h-20, w-5, h-5), fill=palette["structure"]+(0,))
    for x in range(-18, w, 25):
        draw.polygon(((x, h-20), (x+12, h-20), (x+28, h-5), (x+16, h-5)),
                     fill=palette["warning"]+(0,))
    diffuse.paste(image, pos)

    image, draw, pos = patch("grille")
    w, h = image.size
    draw.rectangle((2, 2, w-3, h-3), outline=palette["panel"]+(0,), width=3)
    for y in (12, 31, 50, 69, 88):
        draw.rectangle((11, y, w-12, y+8), fill=palette["metal"]+(0,))
    diffuse.paste(image, pos)

    image, draw, pos = patch("badge")
    w, h = image.size
    draw.line(((17, 42), (17, 24), (40, 13), (40, 25), (63, 13),
               (63, 25), (87, 13), (94, 13), (94, 42), (17, 42)),
              fill=palette["shell_light"]+(0,), width=3)
    font = ImageFont.load_default(size=29)
    text = "VF-12"
    box_ = draw.textbbox((0, 0), text, font=font)
    draw.text(((w-(box_[2]-box_[0]))/2, 52), text, fill=palette["shell_light"]+(0,), font=font)
    draw.rectangle((13, 96, w-14, 101), fill=palette["warning"]+(0,))
    diffuse.paste(image, pos)
    return diffuse, extra


def movement_ranges(s=SPEC):
    return {
        "DoorL": ((-s.door_travel, 0, 0), (0, 0, 0)),
        "DoorR": ((0, 0, 0), (s.door_travel, 0, 0)),
        "Gantry": ((0, 0, s.gantry_move_z_min), (0, 0, s.gantry_move_z_max)),
        "HeadL": ((s.head_move_x_min, s.head_move_y_min, 0), (s.head_move_x_max, s.head_move_y_max, 0)),
        "HeadR": ((s.head_move_x_min, s.head_move_y_min, 0), (s.head_move_x_max, s.head_move_y_max, 0)),
    }


def bounds_record(low, high):
    return dict(min=np.asarray(low).tolist(), max=np.asarray(high).tolist(),
                size=(np.asarray(high)-low).tolist())


def sweep_bounds(root, s=SPEC):
    """Analytic continuous translations + full 360-degree fan envelopes.

    Ancestor moves propagate to heads/locators. Rotation radii use ALL local
    vertices. Final sphere covers all EIGHT corners of the resulting full AABB.
    """
    moves, result = movement_ranges(s), {}
    def visit(piece, parent_min, parent_max):
        a, b = moves.get(piece.name, ((0, 0, 0), (0, 0, 0)))
        pmin, pmax = parent_min + piece.offset + vec(a), parent_max + piece.offset + vec(b)
        if piece.mesh is not None:
            points = np.asarray(piece.mesh.positions)
            lo, hi = points.min(axis=0), points.max(axis=0)
            if piece.name in ("FanL", "FanR"):
                r = float(np.linalg.norm(points[:, (0, 2)], axis=1).max())
                lo[[0, 2]], hi[[0, 2]] = -r, r
            result[piece.name] = bounds_record(pmin+lo, pmax+hi)
        else:
            result[piece.name] = bounds_record(pmin, pmax)
        for child in piece.children:
            visit(child, pmin, pmax)
    visit(root, np.zeros(3), np.zeros(3))
    visible = [result[p.name] for p, _ in walk(root) if p.mesh is not None]
    low = np.min([r["min"] for r in visible], axis=0)
    high = np.max([r["max"] for r in visible], axis=0)
    center = (low+high)/2
    corners = np.asarray(list(itertools.product(*zip(low, high))))
    radius = float(np.linalg.norm(corners-center, axis=1).max()) + 0.002
    return dict(aabb=bounds_record(low, high), sphere_center=center.tolist(),
                sphere_radius=radius, s3o_height=float(high[1]),
                method="continuous linear ranges + exact fan radial extents; sphere over eight AABB corners",
                pieces=result)


def posed_model(root, door_fraction=0, gantry_move_z=0, head_move_y=0, head_move_x=0,
                fan_radians=0, s=SPEC):
    out = copy.deepcopy(root)
    for p, _ in walk(out):
        offset = vec(p.offset)
        if p.name in ("DoorL", "DoorR"):
            offset[0] += (-1 if p.name == "DoorL" else 1)*s.door_travel*door_fraction
        elif p.name == "Gantry":
            offset[2] += gantry_move_z
        elif p.name in ("HeadL", "HeadR"):
            offset += vec((head_move_x, head_move_y, 0))
        elif p.name in ("FanL", "FanR"):
            c, sn = math.cos(fan_radians), math.sin(fan_radians)
            matrix = np.asarray(((c, 0, sn), (0, 1, 0), (-sn, 0, c)))
            p.mesh.positions = (np.asarray(p.mesh.positions) @ matrix.T).tolist()
            p.mesh.normals = (np.asarray(p.mesh.normals) @ matrix.T).tolist()
        p.offset = tuple(offset)
        if p.mesh is not None:
            p.mesh.name += f"__pose_{p.name}"
    return out


def write_native(root, path, sweep):
    write_s3o(root, path, textures=("vehicle_factory_diffuse.tga", "vehicle_factory_material.tga"))
    data = bytearray(path.read_bytes())
    struct.pack_into("<5f", data, 16, sweep["sphere_radius"], sweep["s3o_height"], *sweep["sphere_center"])
    path.write_bytes(data)


def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data)
    if (magic, version, length) != (0x46546C67, 2, len(data)):
        raise ValueError("Invalid GLB header")
    size, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A:
        raise ValueError("Missing GLB JSON")
    document = json.loads(data[20:20+size])
    binary_size, binary_kind = struct.unpack_from("<II", data, 20+size)
    if binary_kind != 0x004E4942:
        raise ValueError("Missing GLB BIN")
    return document, data[28+size:28+size+binary_size]


def accessor(doc, binary, index):
    a = doc["accessors"][index]
    view = doc["bufferViews"][a["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
    dtype = {5126: "<f4", 5125: "<u4"}[a["componentType"]]
    offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    data = np.frombuffer(binary, dtype=dtype, count=a["count"]*width, offset=offset)
    return data if width == 1 else data.reshape(-1, width)


def read_native(path):
    """Legacy empty nodes may declare primitive=2; only non-empty meshes matter."""
    data = path.read_bytes()
    header = struct.unpack_from("<12si5f4i", data)
    if header[:2] != (b"Spring unit\0", 0):
        raise ValueError(f"Invalid S3O header: {path}")
    pieces, visited = {}, set()
    def text(offset):
        return data[offset:data.index(0, offset)].decode("utf-8")
    def visit(offset, parent, origin):
        if offset in visited or offset < 52 or offset + 52 > len(data):
            raise ValueError("Invalid or repeated piece offset")
        visited.add(offset)
        r = struct.unpack_from("<10i3f", data, offset)
        if r[3] < 0 or r[7] < 0 or r[4]+r[3]*32 > len(data) or r[8]+r[7]*4 > len(data):
            raise ValueError("S3O buffer outside file")
        if r[3] and (r[5] != 0 or r[6] != 0 or r[7] % 3):
            raise ValueError("Expected triangle primitives on non-empty mesh")
        name = text(r[0])
        if name in pieces:
            raise ValueError(f"Repeated piece {name}")
        vertices = np.frombuffer(data, dtype="<f4", count=r[3]*8, offset=r[4]).reshape(-1, 8)
        indices = np.frombuffer(data, dtype="<i4", count=r[7], offset=r[8]).reshape(-1, 3)
        local = vec(r[-3:])
        pieces[name] = dict(vertices=vertices, indices=indices, offset=local,
                            position=origin+local, parent=parent)
        for i in range(r[1]):
            visit(struct.unpack_from("<i", data, r[2]+4*i)[0], name, origin+local)
    visit(header[-4], None, np.zeros(3))
    return header, pieces, [text(header[-2]), text(header[-1])]


def piece_stats(root):
    return [dict(name=p.name, parent=PIECE_PARENTS[p.name], offset_world=list(p.offset),
                 mesh=p.mesh.name if p.mesh is not None else None,
                 triangles=len(p.mesh.indices)//3 if p.mesh is not None else 0,
                 vertices=len(p.mesh.positions) if p.mesh is not None else 0)
            for p, _ in walk(root)]


def references():
    """Read-only sources: SP-6 is explicitly splayed, never the exchange rest tree."""
    spider = build_spider.make_model()  # Initializes that source's LEG_YAW map.
    m1 = build_m1a1.make_model()
    models = {"spider": build_spider.posed_for_preview(spider), "m1a1": m1,
              "scout": build_scout.make_model()}
    records = {}
    for name in PRODUCTS:
        native_name = {"stumpy": "Stumpy", "flare": "Flare", "duron": "Duron"}.get(name, name)
        path = ROOT / "Objects3d" / (native_name + ".s3o")
        _, pieces, _ = read_native(path)
        points = np.concatenate([p["vertices"][:, :3]+p["position"] for p in pieces.values() if len(p["vertices"])])
        same_source = None
        if name in models:
            original = spider if name == "spider" else models[name]
            same_source = set(pieces) == {p.name for p, _ in walk(original)}
            for p, _ in walk(original):
                if not same_source:
                    break
                actual = pieces[p.name]
                same_source = bool(np.allclose(actual["offset"], p.offset, atol=1e-5))
                if p.mesh is not None:
                    same_source = same_source and actual["vertices"].shape[0] == len(p.mesh.positions) \
                        and np.allclose(actual["vertices"][:, :3], p.mesh.positions, atol=1e-5) \
                        and np.array_equal(actual["indices"].ravel(), p.mesh.indices)
            low, high = model_bounds(models[name])
        else:
            low, high = points.min(axis=0), points.max(axis=0)
        records[name] = dict(native_model=path.relative_to(ROOT).as_posix(),
            native_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            effective_pose="posed_for_preview (rest hip yaw)" if name == "spider" else "native idle / zero weapon angles",
            bounds_world=bounds_record(low, high), generated_source_matches_native=same_source,
            is_factory_product=name in PRODUCTS, inherited_below_ground_world=max(0.0, -float(low[1])))
    return models, records


def positive_overlap(a_low, a_high, b_low, b_high, tolerance=1e-6):
    return bool(np.all(np.minimum(a_high, b_high)-np.maximum(a_low, b_low) > tolerance))


def space_checks(root, refs, s=SPEC):
    sweep = sweep_bounds(root, s)
    fixed = root.mesh.components
    open_doors = {}
    for piece, offset in walk(posed_model(root, door_fraction=1, s=s)):
        if piece.name in ("DoorL", "DoorR"):
            points = np.asarray(piece.mesh.positions)+offset
            open_doors[piece.name] = bounds_record(points.min(axis=0), points.max(axis=0))
    def exit_hits(low, high):
        hits = [c["name"] for c in fixed if positive_overlap(low, high, c["min"], c["max"])]
        moving = dict(open_doors)
        moving.update({name+"_full_sweep": sweep["pieces"][name]
                       for name in ("Gantry", "HeadL", "HeadR")})
        hits += [name for name, b in moving.items()
                 if positive_overlap(low, high, b["min"], b["max"])]
        return hits
    rows = []
    def result(name, passed, **evidence):
        rows.append(dict(name=name, status="PASS" if passed else "FAIL", **evidence))
    result("visual_sweep_within_192x160_footprint",
           max(abs(sweep["aabb"]["min"][0]), abs(sweep["aabb"]["max"][0])) <= s.footprint_x*s.footprint_cell_world/2+1e-6
           and max(abs(sweep["aabb"]["min"][2]), abs(sweep["aabb"]["max"][2])) <= s.footprint_z*s.footprint_cell_world/2+1e-6,
           sweep_aabb_world=sweep["aabb"], native_placement="NOT_RUN")
    for door in ("DoorL", "DoorR"):
        b = sweep["pieces"][door]
        hit = [c["name"] for c in fixed if positive_overlap(b["min"], b["max"], c["min"], c["max"])]
        result(door+"_continuous_travel_avoids_fixed_solids", not hit,
               method="whole swept slab AABB versus each fixed component AABB (conservative)", hits=hit,
               swept_aabb_world=b, slot_depth_world=4.5, leaf_depth_world=s.door_thickness,
               front_and_rear_clearance_world=(4.5-s.door_thickness)/2,
               outer_end_clearance_world=1.0, top_clearance_world=s.lintel_bottom_y-s.door_top_y)
    for name in ("Gantry", "HeadL", "HeadR"):
        b = sweep["pieces"][name]
        hits = [c["name"] for c in fixed if positive_overlap(b["min"], b["max"], c["min"], c["max"])]
        result(name+"_full_travel_avoids_fixed_solids", not hits, hits=hits,
               swept_aabb_world=b, method="all fixed component AABBs versus continuous ancestor-aware sweep")
    tool_min = min(sweep["pieces"][h]["min"][1] for h in ("HeadL", "HeadR"))
    result("reference_generators_match_native_geometry",
           all(refs[n]["generated_source_matches_native"] for n in ("spider", "m1a1", "scout")))
    result("tools_minimum_full_travel_height", tool_min >= 48-1e-6,
           lowest_world_y=tool_min, includes_parent_gantry_move=True)
    gantry = next(p for p, _ in walk(root) if p.name == "Gantry")
    beam = next(c for c in gantry.mesh.components if c["name"] == "bridge_beam")
    for head in ("HeadL", "HeadR"):
        p = next(p for p, _ in walk(root) if p.name == head)
        guide = next(c for c in p.mesh.components if c["name"] == "head_guide_shank")
        engagement = p.offset[1]+s.head_move_y_min+guide["max"][1]-beam["min"][1]
        result(head+"_guide_stays_engaged_at_lowest_travel", engagement > 0,
               minimum_vertical_engagement_world=engagement,
               intentional_joint="sliding shank enters bridge; carriage does not float")
    for fan in ("FanL", "FanR"):
        p = next(p for p, _ in walk(root) if p.name == fan)
        r = float(np.linalg.norm(np.asarray(p.mesh.positions)[:, (0, 2)], axis=1).max())
        # A polygonal 12-sided hole has smaller inradius than its vertex radius.
        hole_inradius = 12.5*math.cos(math.pi/12)
        ylo = min(point[1] for point in p.mesh.positions)+p.offset[1]
        yhi = max(point[1] for point in p.mesh.positions)+p.offset[1]
        result(fan+"_continuous_rotation_clearance", r < hole_inradius and ylo > 29.01 and yhi < 32,
               blade_sweep_radius_world=r, housing_minimum_inner_radius_world=hole_inradius,
               minimum_radial_gap_world=hole_inradius-r, angle_range_radians=[0, math.tau],
               bottom_clearance_world=ylo-29.01, top_clearance_world=32-yhi)
    # Product AABBs are swept continuously from BuildSpot until the rear of the
    # product is outside the foundation. This is a VISUAL straight-line test,
    # not a YardMap/pathfinding test and not a weapon/gait animation simulation.
    for name, ref in refs.items():
        low, high = vec(ref["bounds_world"]["min"]), vec(ref["bounds_world"]["max"])
        finish_z = s.foundation_half_z-low[2]+4
        path_low = low+vec((0, s.floor_y, s.build_z))
        path_high = high+vec((0, s.floor_y, finish_z))
        # Old product meshes include pre-existing below-ground triangles. Keep
        # them in the record; exclude only that sub-ground region in this test.
        path_low[1] = max(s.floor_y+1e-5, path_low[1])
        hit = exit_hits(path_low, path_high)
        margins = dict(left=s.lane_half_x+float(low[0]), right=s.lane_half_x-float(high[0]),
                       lintel=s.lintel_bottom_y-(float(high[1])+s.floor_y),
                       lowest_tool=tool_min-(float(high[1])+s.floor_y),
                       rear_wall=s.build_z+float(low[2])-s.rear_inner_z)
        result(name+"_idle_envelope_straight_exit", not hit and min(margins.values()) > 0,
               is_product=ref["is_factory_product"], margins_world=margins, hits=hit,
               build_origin_world=[0, s.floor_y, s.build_z], exit_origin_z_world=float(finish_z),
               inherited_subground_geometry_world=ref["inherited_below_ground_world"],
               native_ground_and_pathfinding="NOT_RUN", weapon_and_gait_sweeps="not part of this idle-only row")
    proxies = dict(PRODUCT_MOTION_PROXIES)
    for name, proxy in proxies.items():
        result(name+"_motion_proxy_input_hash", refs[name]["native_sha256"] == proxy["nativeSha256"],
               expected_native_sha256=proxy["nativeSha256"], current_native_sha256=refs[name]["native_sha256"])
    proxies["all_four_products_R40"] = dict(horizontalRadiusWorld=40.0, minYWorld=-1.344,
        maxYWorld=max(p["maxYWorld"] for p in PRODUCT_MOTION_PROXIES.values()),
        jointRanges="union of the four stated motion proxies; all horizontal body headings")
    for name, proxy in proxies.items():
        radius = proxy["horizontalRadiusWorld"]+PROXY_ROUNDING_PAD
        top = proxy["maxYWorld"]+s.floor_y+PROXY_ROUNDING_PAD
        finish_z = s.foundation_half_z+radius+4
        low, high = vec((-radius, s.floor_y+1e-5, s.build_z-radius)), vec((radius, top, finish_z+radius))
        hits = exit_hits(low, high)
        margins = dict(each_side=s.lane_half_x-radius, lintel=s.lintel_bottom_y-top,
                       lowest_tool=tool_min-top, rear_wall=s.build_z-radius-s.rear_inner_z)
        result(name+"_full_motion_3d_proxy_exit", not hits and min(margins.values()) > 0,
               source_evidence=PRODUCT_PROXY_EVIDENCE, proxy=proxy,
               report_values_rederived_here=False, rounding_pad_world=PROXY_ROUNDING_PAD,
               method="conservative 3D proxy swept continuously along +Z versus each actual fixed-component AABB and full factory-motion AABBs",
               swept_proxy_aabb_world=bounds_record(low, high), margins_world=margins, hits=hits,
               body_heading_radians=[0, math.tau], center_path_x_world=0,
               build_origin_world=[0, s.floor_y, s.build_z], exit_origin_z_world=finish_z,
               inherited_subground_geometry_world=max(0.0, -proxy["minYWorld"]),
               scope="flat ground, known joint ranges, doors fully open; not M1A1; no terrain pitch/roll or lateral path wandering",
               native_gait_aim_ground_pathfinding="NOT_RUN")
    return rows


def asset_checks(root, sweep, gray=False):
    checks = []
    def run(name, operation):
        try:
            operation()
            checks.append(dict(name=name, status="PASS"))
        except (AssertionError, ValueError, KeyError, IndexError, OSError) as error:
            checks.append(dict(name=name, status="FAIL", reason=str(error)))
    stats = piece_stats(root)
    def geometry():
        assert len(stats) == 12 and {p["name"] for p in stats} == set(PIECE_PARENTS)
        names = [p["mesh"] for p in stats if p["mesh"] is not None]
        assert len(names) == len(set(names)), "Mesh names must be unique for each variant"
        assert sum(p["triangles"] for p in stats) <= TRIANGLE_REVIEW_LIMIT
        for p, _ in walk(root):
            if p.mesh is None:
                assert p.name in ("NanoL", "NanoR", "BuildSpot")
                continue
            a = np.column_stack((p.mesh.positions, p.mesh.normals, p.mesh.uvs))
            ix = np.asarray(p.mesh.indices).reshape(-1, 3)
            assert np.isfinite(a).all(), p.name+" non-finite data"
            assert ix.min() >= 0 and ix.max() < len(a), p.name+" index out of bounds"
            assert np.allclose(np.linalg.norm(a[:, 3:6], axis=1), 1, atol=1e-6), p.name+" normal length"
            assert np.all((a[:, 6:] >= 0) & (a[:, 6:] <= 1)), p.name+" UV range"
            cross = np.cross(a[ix[:, 1], :3]-a[ix[:, 0], :3], a[ix[:, 2], :3]-a[ix[:, 0], :3])
            assert np.all(np.linalg.norm(cross, axis=1) > 1e-7), p.name+" degenerate triangle"
            n = a[ix, 3:6]
            assert np.all(np.sum(cross*n[:, 0], axis=1) > 0), p.name+" winding"
            assert np.allclose(n[:, 0], n[:, 1]) and np.allclose(n[:, 0], n[:, 2]), p.name+" not flat-shaded"
    run("finite_normals_uvs_indices_winding_unique_meshes_12_nodes", geometry)
    try:
        header, native, textures = read_native(ROOT / "Objects3d" / "vehicle_factory.s3o")
        doc, binary = read_glb(ROOT / "Objects3d" / "vehicle_factory.glb")
    except (OSError, ValueError, struct.error) as error:
        return checks+[dict(name="read_native_and_exchange", status="FAIL", reason=str(error))]
    def equality():
        nodes = {n["name"]: n for n in doc["nodes"]}
        assert len(nodes) == len(doc["nodes"]) == len(stats) == len(native)
        assert set(nodes) == set(native) == set(PIECE_PARENTS)
        parents = {child: n["name"] for n in doc["nodes"] for child in n.get("children", [])}
        generated = {p.name: p for p, _ in walk(root)}
        for i, node in enumerate(doc["nodes"]):
            name, p = node["name"], generated[node["name"]]
            n = native[name]
            assert parents.get(i) == n["parent"] == PIECE_PARENTS[name]
            np.testing.assert_allclose(node["translation"], p.offset, atol=1e-6)
            np.testing.assert_allclose(n["offset"], p.offset, atol=1e-6)
            if p.mesh is None:
                assert "mesh" not in node and len(n["vertices"]) == 0
                continue
            primitive = doc["meshes"][node["mesh"]]["primitives"][0]
            for field, columns in (("POSITION", slice(0, 3)), ("NORMAL", slice(3, 6)), ("TEXCOORD_0", slice(6, 8))):
                np.testing.assert_array_equal(accessor(doc, binary, primitive["attributes"][field]), n["vertices"][:, columns])
            np.testing.assert_array_equal(accessor(doc, binary, primitive["indices"]), n["indices"].ravel())
            np.testing.assert_allclose(n["vertices"][:, :3], p.mesh.positions, atol=1e-5)
            np.testing.assert_allclose(n["vertices"][:, 3:6], p.mesh.normals, atol=1e-6)
            uv = np.asarray(p.mesh.uvs).copy()
            uv[:, 1] = 1-uv[:, 1]
            np.testing.assert_allclose(n["vertices"][:, 6:], uv, atol=1e-7)
        assert "animations" not in doc and "skins" not in doc
    run("source_s3o_glb_geometry_uvs_hierarchy_match_static_rigid", equality)
    def textures_check():
        assert textures == ["vehicle_factory_diffuse.tga", "vehicle_factory_material.tga"]
        first = Image.open(ROOT/"UnitTextures"/textures[0]).convert("RGBA")
        second = Image.open(ROOT/"UnitTextures"/textures[1]).convert("RGBA")
        assert first.size == second.size == (ATLAS_SIZE, ATLAS_SIZE)
        expected_first, expected_second = make_atlas(gray)
        np.testing.assert_array_equal(first, expected_first)
        np.testing.assert_array_equal(second, expected_second)
        assert second.getchannel("A").getextrema() == (255, 255)
        assert second.getchannel("R").getextrema() == (0, 0)
        if gray:
            a = np.asarray(first)
            assert np.array_equal(a[:, :, 0], a[:, :, 1]) and np.array_equal(a[:, :, 1], a[:, :, 2])
            assert first.getchannel("A").getextrema() == (0, 0)
        view = doc["bufferViews"][doc["images"][0]["bufferView"]]
        start = view.get("byteOffset", 0)
        embedded = np.asarray(Image.open(io.BytesIO(binary[start:start+view["byteLength"]])).convert("RGBA"))
        np.testing.assert_array_equal(embedded[:, :, :3], np.asarray(first)[:, :, :3])
        np.testing.assert_array_equal(embedded[:, :, 3], np.asarray(second)[:, :, 3])
        assert len(doc["materials"]) == 1
    run("atlas_channels_and_glb_embedded_visibility", textures_check)
    def containment():
        center, radius = vec(header[4:7]), header[2]
        aabb = sweep["aabb"]
        corners = np.asarray(list(itertools.product(*zip(aabb["min"], aabb["max"]))))
        assert np.max(np.linalg.norm(corners-center, axis=1)) <= radius+1e-5
        np.testing.assert_allclose(center, sweep["sphere_center"], atol=1e-5)
        assert header[3] >= aabb["max"][1]-1e-5
        # Also exercise real transformed vertices at endpoints/intermediates,
        # while the analytic envelope above proves the continuous ranges.
        for door, gz, hy, hx, fan in itertools.product((0, .5, 1), (0, 14, 28), (-5, 0), (-4, 4), (0, .37, 1.1)):
            for p, offset in walk(posed_model(root, door, gz, hy, hx, fan)):
                if p.mesh is not None:
                    points = np.asarray(p.mesh.positions)+offset
                    assert np.max(np.linalg.norm(points-center, axis=1)) <= radius+1e-4
    run("s3o_sphere_contains_full_continuous_motion_and_sampled_vertices", containment)
    def data_contract():
        data_path = ROOT/"Scripts"/"vehicle_factory_data.lua"
        assert data_path.read_text(encoding="utf-8") == parameter_lua(root, sweep, gray=gray), \
            "Generated Lua contract differs from current source; rebuild it"
    run("generated_lua_contract_matches_current_geometry", data_contract)
    return checks


def xyz(value):
    return dict(zip(("x", "y", "z"), map(float, value)))


def make_parameters(root, sweep, s=SPEC, gray=False):
    stats = piece_stats(root)
    return dict(schemaVersion=1, stage="neutral geometry inspection" if gray else "G2 finished industrial asset", lengthUnit="Recoil world unit (not metre)",
        rotationUnit="radian", axisConvention="X right; Y up; +Z exit; piece offsets parent-local",
        nativeValidation="EXTERNAL_REPORT_REQUIRED", animationStorage="Lua rigid pieces; GLB has no animation clips",
        buildProducts=list(PRODUCTS),
        normalProductionPose="facing factory +Z; neutral weapons; SP-6 splayed idle; actual engine trajectory separate",
        footprint=dict(unitDefX=s.footprint_x, unitDefZ=s.footprint_z,
            unitDefCellWorld=s.footprint_cell_world, gameSquareWorld=s.game_square_world,
            engineXSize=24, engineZSize=20, worldX=192, worldZ=160,
            basis="Recoil 2026.07.04 input-cell conversion; placement evidence belongs to the source-hashed native report"),
        yardMapCandidate=dict(rows=["oooooooooooo"]*2 + ["ooooccccoooo"]*8,
            rowOrder="facing=0: first text row is rear -Z, last row is front +Z",
            alwaysBlockedCharacter="o", openOnlyWhenYardOpenCharacter="c",
            passageCellsWide=4, passageWorldWidth=64,
            rearBlockedRows=2, stateContract="Native factory may pre-open yard; admit production only after both doors are open and yard is accepted",
            characterProbeEvidence="mygame-factory-yard-probe-iihn531x/yardmap_probe.json (coordinator native probe)",
            characterSemantics="PASS in coordinator's probe; probe used one rear blocked row",
            candidateValidation="EXTERNAL_REPORT_REQUIRED: two-row passage, all four facings and mixed queues"),
        foundation=dict(halfXWorld=s.foundation_half_x, halfZWorld=s.foundation_half_z,
                        driveFloorYWorld=s.floor_y, skirtBottomYWorld=s.skirt_bottom_y),
        buildSpot=dict(piece="BuildSpot", positionWorld=xyz((0, s.floor_y, s.build_z))),
        corridor=dict(minXWorld=-s.lane_half_x, maxXWorld=s.lane_half_x,
            rearInnerZWorld=s.rear_inner_z, apronFrontZWorld=s.foundation_half_z,
            clearWidthWorld=2*s.lane_half_x, lintelBottomYWorld=s.lintel_bottom_y,
            clearHeightAboveFloorWorld=s.lintel_bottom_y-s.floor_y),
        productClearanceProxy=dict(evidence=PRODUCT_PROXY_EVIDENCE,
            method="coordinator native-vertex analytical motion bounds; not runtime pose measurements",
            products=copy.deepcopy(PRODUCT_MOTION_PROXIES),
            proxyProducts=list(PRODUCT_MOTION_PROXIES), notCoveredProducts=["scout", "m1a1"],
            conservativeHorizontalRadiusWorld=40.0,
            roundingPadWorld=PROXY_ROUNDING_PAD,
            maximumProductYWorld=max(p["maxYWorld"] for p in PRODUCT_MOTION_PROXIES.values()),
            scope="flat ground, center path X=0, arbitrary body yaw; explicit joint ranges; M1A1 excluded",
            nativeMotionValidation="EXTERNAL_REPORT_REQUIRED"),
        door=dict(leftPiece="DoorL", rightPiece="DoorR", moveAxis="x", closedMoveWorld=0,
            leftOpenMoveWorld=-s.door_travel, rightOpenMoveWorld=s.door_travel,
            travelWorld=s.door_travel, leafWidthWorld=s.lane_half_x,
            leafHeightWorld=s.door_top_y-s.door_bottom_y, leafThicknessWorld=s.door_thickness,
            closedLeftXWorld=-s.lane_half_x/2, closedRightXWorld=s.lane_half_x/2,
            pivotYWorld=(s.door_top_y+s.door_bottom_y)/2, planeZWorld=s.door_z,
            bottomYWorld=s.door_bottom_y, topYWorld=s.door_top_y,
            pocketInnerAbsXWorld=s.lane_half_x, pocketOuterAbsXWorld=s.lane_half_x+s.door_travel+1,
            pocketMinZWorld=s.door_z-2.25, pocketMaxZWorld=s.door_z+2.25,
            pocketTopYWorld=s.lintel_bottom_y,
            releaseContract="Both doors reach full travel before INBUILDSTANCE admits production; native yard may pre-open"),
        gantry=dict(piece="Gantry", moveAxis="z", pivotWorld=xyz((0, s.gantry_y, s.gantry_z)),
            minMoveWorld=s.gantry_move_z_min, maxMoveWorld=s.gantry_move_z_max,
            minPivotZWorld=s.gantry_z+s.gantry_move_z_min,
            maxPivotZWorld=s.gantry_z+s.gantry_move_z_max),
        heads=dict(leftPiece="HeadL", rightPiece="HeadR", nanoLeftPiece="NanoL", nanoRightPiece="NanoR",
            leftParentOffsetWorld=xyz((-s.head_x, -1, 0)), rightParentOffsetWorld=xyz((s.head_x, -1, 0)),
            nanoLocalOffsetWorld=xyz((0, -8, 0)), minXMoveWorld=s.head_move_x_min,
            maxXMoveWorld=s.head_move_x_max, minYMoveWorld=s.head_move_y_min,
            maxYMoveWorld=s.head_move_y_max, minimumTipYWorld=sweep["pieces"]["HeadL"]["min"][1]),
        fans=dict(axis="y", leftPiece="FanL", rightPiece="FanR", minAngleRadians=0,
                  maxAngleRadians=math.tau, fullContinuousRotation=True),
        workLamp=dict(piece="WorkLamp", defaultVisible=True, nativeEmission=0,
                      meaning="single status face; hiding/showing in Lua, no baked emission state"),
        bounds=dict(closed=bounds_record(*model_bounds(root)),
            opened=bounds_record(*model_bounds(posed_model(root, door_fraction=1))), fullMotion=sweep),
        pieces=stats, totals=dict(nodes=len(stats), meshNodes=sum(p["mesh"] is not None for p in stats),
            triangles=sum(p["triangles"] for p in stats), vertices=sum(p["vertices"] for p in stats),
            materialSlots=1, atlasSize=ATLAS_SIZE))


def lua_literal(value, level=0):
    indent, child = "    "*level, "    "*(level+1)
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Lua data cannot contain non-finite numbers")
        return format(value, ".17g")
    entries = [f"{key} = {lua_literal(v, level+1)}," for key, v in value.items()] \
        if isinstance(value, dict) else [lua_literal(v, level+1)+"," for v in value]
    return "{\n"+"\n".join(child+entry for entry in entries)+"\n"+indent+"}"


def parameter_lua(root, sweep, gray=False):
    return ("-- Generated ONLY by tools/build_vehicle_factory.py. Do not hand-edit.\n"
        "-- Parent-local offsets and Move deltas are distinct. Lengths: Recoil world units.\n"
        "-- Geometry/material contract; native validation lives in the source-hashed test report.\nreturn "
        +lua_literal(make_parameters(root, sweep, gray=gray))+"\n")


def comparison_atlas(factory_atlas, factory_extra, gray=False):
    # Equal-size packed tiles preserve each source's UVs and visibility mask.
    sources = [(factory_atlas, factory_extra), build_spider.make_atlas(), build_m1a1.make_atlas()]
    atlas = Image.new("RGBA", (ATLAS_SIZE*3, ATLAS_SIZE))
    extra = Image.new("RGBA", atlas.size, (0, 10, 0, 255))
    for i, (a, b) in enumerate(sources):
        a = a.resize((ATLAS_SIZE, ATLAS_SIZE), Image.Resampling.NEAREST)
        b = b.resize((ATLAS_SIZE, ATLAS_SIZE), Image.Resampling.NEAREST)
        if gray:
            a = a.convert("L").convert("RGBA")
            a.putalpha(0)
        atlas.paste(a, (i*ATLAS_SIZE, 0))
        extra.paste(b, (i*ATLAS_SIZE, 0))
    return atlas, extra


def scene_copy(model, prefix, atlas_slot, translation=(0, 0, 0)):
    root = copy.deepcopy(model)
    root.offset = tuple(vec(root.offset)+vec(translation))
    for p, _ in walk(root):
        p.name = prefix+p.name
        if p.mesh is not None:
            p.mesh = copy.deepcopy(p.mesh)
            p.mesh.name = prefix+p.name+"_mesh"
            uv = np.asarray(p.mesh.uvs).copy()
            uv[:, 0] = (uv[:, 0]+atlas_slot)/3
            p.mesh.uvs = uv.tolist()
    return root


def caption(image, path, title, subtitle=""):
    out = image.copy()
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, out.width, 63 if subtitle else 39), fill=(239, 240, 235, 255))
    draw.text((18, 8), title, fill=(44, 48, 47), font=ImageFont.load_default(size=22))
    if subtitle:
        draw.text((18, 36), subtitle, fill=(66, 70, 68), font=ImageFont.load_default(size=15))
    out.save(path)
    return out


def make_preview_images(root, atlas, extra, reference_models, gray=False):
    directory = PREVIEWS / ("neutral" if gray else "final")
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    def view(name, model, title, eye, target=(0, 28, 0), size=(1500, 1000), subtitle=None, a=atlas, b=extra):
        if subtitle is None:
            subtitle = "OFFLINE NEUTRAL INSPECTION" if gray else "OFFLINE FINISHED ASSET | native validation recorded separately"
        path = directory/(name+".png")
        image = render(model, a, b, path, eye=eye, target=target, width=size[0], height=size[1])
        caption(image, path, title, subtitle)
        files.append(path)
        print("Rendered", path.name, flush=True)
        return image
    opened = posed_model(root, door_fraction=1)
    view("front_closed", root, "FRONT / CLOSED", (0, 28, 250), size=(1500, 850))
    view("front_open", opened, "FRONT / OPEN", (0, 28, 250), size=(1500, 850))
    view("side", opened, "RIGHT SIDE / COOLING POD", (250, 28, 0), size=(1500, 900))
    view("side_control", opened, "LEFT SIDE / CONTROL CABIN", (-250, 28, 0), size=(1500, 900))
    view("top", opened, "TOP / OPEN ASSEMBLY BAY", (0, 250, 0), target=(0, 0, 0), size=(1400, 1300))
    view("rts_closed", root, "RTS / CLOSED", (195, 200, 240), size=(1600, 1100))
    view("rts_open", opened, "RTS / OPEN", (195, 200, 240), size=(1600, 1100))
    view("rear", opened, "REAR / WORKSHOP AND SERVICE VOLUMES", (-195, 170, -240), size=(1500, 1050))
    working = posed_model(root, door_fraction=1, gantry_move_z=28, head_move_y=-5, head_move_x=4, fan_radians=.4)
    view("working_limit", working, "WORKING LIMIT / HEADS AT LOWEST Y=48", (195, 150, 250), size=(1600, 1100))
    cutaway = posed_model(root, door_fraction=.5)
    excluded = {f"pocket_{label}_{part}" for label in ("L", "R") for part in ("front_skin", "top_cap")}
    keep = [c for c in cutaway.mesh.components if c["name"] not in excluded]
    cutaway.mesh.indices = sum([cutaway.mesh.indices[c["index_start"]:c["index_start"]+c["index_count"]] for c in keep], [])
    cutaway.mesh.name = "vehicle_factory_pocket_section_only"
    view("door_pocket_section", cutaway, "DOOR POCKET SECTION / 50% TRAVEL", (155, 110, 250),
         subtitle="INSPECTION CUTAWAY ONLY | front pocket skins and caps hidden; exported asset is complete", size=(1600, 1000))

    common, visibility = comparison_atlas(atlas, extra, gray)
    common.save(directory/"comparison_atlas.png")
    visibility.save(directory/"comparison_visibility.png")
    factory = scene_copy(opened, "Factory_", 0)
    spider = scene_copy(reference_models["spider"], "SP6_", 1, (-43, 0, 108))
    m1 = scene_copy(reference_models["m1a1"], "M1A1_", 2, (41, 0, 139))
    scene = Piece("ScaleScene", (0, 0, 0), None, [factory, spider, m1])
    view("actual_scale_scene", scene, "ACTUAL SCALE / FACTORY + SP-6 + M1A1", (245, 255, 330), target=(0, 22, 68),
         size=(1800, 1350), subtitle="ONE SCENE, ONE CAMERA | all model scales = 1 | SP-6 uses posed_for_preview", a=common, b=visibility)
    view("actual_scale_top", scene, "ACTUAL SCALE / TOP", (0, 350, 60), target=(0, 0, 60), size=(1400, 1700),
         subtitle="ONE SCENE | SP-6 at (-43,0,108), M1A1 at (41,0,139) | world units, not metres", a=common, b=visibility)
    assembly = Piece("AssemblyScene", (0, 0, 0), None, [scene_copy(opened, "Factory_", 0),
        scene_copy(reference_models["spider"], "Product_", 1, (0, SPEC.floor_y, SPEC.build_z))])
    view("sp6_at_buildspot", assembly, "SP-6 AT BUILDSPOT / OPEN FACTORY", (170, 335, 255), size=(1600, 1200),
         subtitle="OFFLINE PRODUCTION POSE | actual engine production and movement checked separately", a=common, b=visibility)
    pair = Piece("SpacingScene", (0, 0, 0), None, [
        scene_copy(opened, "FactoryA_", 0, (-144, 0, 0)),
        scene_copy(opened, "FactoryB_", 0, (144, 0, 0)),
        scene_copy(reference_models["spider"], "SP6_", 1, (0, 0, 12))])
    view("repeated_factory_spacing", pair, "TWO FACTORIES / 96-WORLD-UNIT GAP / ACTUAL SCALE",
         (300, 500, 390), target=(0, 25, 0), size=(1800, 1100),
         subtitle="OFFLINE DENSITY CHECK | centres 288 apart | not an adjacent-placement or pathfinding test", a=common, b=visibility)
    # Separate framings are intentionally labelled, NEVER used for scale proof.
    a_path, b_path = directory/"style_factory_panel.png", directory/"style_m1a1_panel.png"
    a = render(factory, common, visibility, a_path, eye=(180, 173, 215), target=(0, 28, 0), width=900, height=720)
    b = render(scene_copy(reference_models["m1a1"], "M1_", 2), common, visibility, b_path,
               eye=(180, 161, 215), target=(0, 16, 0), width=900, height=720)
    sheet = Image.new("RGBA", (1800, 800), (226, 230, 221, 255))
    sheet.paste(a, (0, 80)); sheet.paste(b, (900, 80))
    style_path = directory/"style_density_only.png"
    caption(sheet, style_path, "SIMILAR SCREEN SIZE / FACETS, PALETTE AND DETAIL DENSITY",
            "INDEPENDENT FRAMING - NOT ACTUAL SCALE | factory left, M1A1 right")
    files.append(style_path)
    return files


def make_icon(root, atlas, extra):
    path = ROOT/"UnitPics"/"vehicle_factory.png"
    image = render(posed_model(root, door_fraction=1), atlas, extra, path,
                   eye=(180, 173, 215), target=(0, 28, 0), width=512, height=512, transparent=True)
    image.resize((256, 256), Image.Resampling.LANCZOS).save(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    colors = parser.add_mutually_exclusive_group()
    colors.add_argument("--gray", dest="gray", action="store_true", help="Neutral inspection version of the current geometry")
    colors.add_argument("--final", dest="gray", action="store_false", help="Finished industrial palette (default)")
    parser.set_defaults(gray=False)
    parser.add_argument("--no-preview", action="store_true", help="Skip studio views; still generate the runtime icon")
    parser.add_argument("--check-only", action="store_true", help="Check source and current exports without writing anything")
    args = parser.parse_args()
    root = make_model()
    sweep = sweep_bounds(root)
    models, refs = references()
    spaces = space_checks(root, refs)
    if args.check_only:
        checks = asset_checks(root, sweep, args.gray)+spaces
        for row in checks:
            print(row["status"], row["name"], row.get("reason", ""))
        if any(r["status"] == "FAIL" for r in checks):
            raise SystemExit(1)
        return

    for directory in (ROOT/"Objects3d", ROOT/"UnitTextures", ROOT/"Scripts", ROOT/"UnitPics", PREVIEWS):
        directory.mkdir(parents=True, exist_ok=True)
    atlas, extra = make_atlas(args.gray)
    atlas.save(ROOT/"UnitTextures"/"vehicle_factory_diffuse.tga", compression=None)
    extra.save(ROOT/"UnitTextures"/"vehicle_factory_material.tga", compression=None)
    write_native(root, ROOT/"Objects3d"/"vehicle_factory.s3o", sweep)
    write_glb(root, atlas, extra, ROOT/"Objects3d"/"vehicle_factory.glb",
              generator="MyGame Vehicle Factory / static rigid hierarchy / no baked animation")
    parameters = make_parameters(root, sweep, gray=args.gray)
    data_path = ROOT/"Scripts"/"vehicle_factory_data.lua"
    data_path.write_text(parameter_lua(root, sweep, gray=args.gray), encoding="utf-8")
    checks = asset_checks(root, sweep, args.gray)
    make_icon(root, atlas, extra)
    images = [] if args.no_preview else make_preview_images(root, atlas, extra, models, args.gray)
    stats = piece_stats(root)
    failures = [r for r in checks+spaces if r["status"] == "FAIL"]
    manifest = dict(schema_version=1, name="Vehicle Factory", stage=parameters["stage"],
        authority_source="tools/build_vehicle_factory.py", style="M1A1 v1 flat-shaded low-poly / building adaptation",
        differences_from_tank="Building-scale hollow workshop, continuous lane, real lateral door pockets, stable foundation; no tank proportions or sand palette",
        review_ceiling_triangles=TRIANGLE_REVIEW_LIMIT, budget_source="VEHICLE_FACTORY.md task budget; geometry is allocated by functional/readability value",
        triangles=parameters["totals"]["triangles"], vertices=parameters["totals"]["vertices"], nodes=len(stats),
        pieces=[p["name"] for p in stats], piece_statistics=stats, material_slots=1, texture_size=[ATLAS_SIZE, ATLAS_SIZE],
        coordinates="X right, Y up, Z exit; world units, not metres",
        native_model="Objects3d/vehicle_factory.s3o", exchange_model="Objects3d/vehicle_factory.glb",
        parameter_data="Scripts/vehicle_factory_data.lua", parameters=parameters,
        static_components=root.mesh.components, references=refs, asset_checks=checks, space_checks=spaces,
        previews=[p.relative_to(ROOT).as_posix() for p in images],
        scale_scene=dict(single_combined_render=True, all_scales=[1, 1, 1],
            factory_origin_world=[0, 0, 0], spider_origin_world=[-43, 0, 108], m1a1_origin_world=[41, 0, 139],
            spider_pose="posed_for_preview", texture_method="one packed per-asset atlas with remapped UVs and original visibility; grayscale only in --gray mode",
            style_density_sheet_is_not_scale_evidence=True),
        repeated_pair=dict(factory_centres_world=[[-144, 0, 0], [144, 0, 0]],
            visual_gap_world=96, factory_only_triangles=2*parameters["totals"]["triangles"],
            factory_only_vertices=2*parameters["totals"]["vertices"], factory_only_nodes=24,
            mixed_base_layout="EXTERNAL_REPORT_REQUIRED", native_adjacency="EXTERNAL_REPORT_REQUIRED"),
        state_geometry_peak=dict(triangles=parameters["totals"]["triangles"], vertices=parameters["totals"]["vertices"],
            nodes=12, note="All parts visible. No additional work/damage meshes. Hidden lamp only reduces count."),
        glb_material_limit="Single inherited preview PBR material; embedded RGB/visibility matches native atlases, native reflection G not a PBR roughness map",
        verification=dict(G1="FAIL" if failures else "NOT_RUN", G2="NOT_RUN", G3="NOT_RUN", G4="NOT_RUN"),
        verification_scope=dict(static_geometry_and_space="FAIL" if failures else "PASS",
            preview_rendering="NOT_RUN" if args.no_preview else "PASS",
            visual_review="EXTERNAL_REPORT_REQUIRED: image generation does not award a style gate",
            native_report="tools/previews/vehicle_factory/acceptance/engine_report.json",
            source_hashed_delivery="tools/previews/vehicle_factory/acceptance/verification.json",
            G3="Static geometry/export contract only here; controller and native behavior have separate tests"),
        limitations=["This generator does not run the engine, UnitDefs, YardMap, Lua state machine or native production tests.",
            "Four facings, continuous production, rally changes, congestion, adjacency and spider construction require the separate source-hashed native report.",
            "Analytical motion proxies are not native gait/aim interpolation or terrain-tilt evidence.",
            "The four historical product proxies are supplied measurements; test_vehicle_factory.py independently re-derives them from pinned native meshes.",
            "Stumpy, Flare and Duron retain pre-existing sub-ground vertices; records expose depths rather than claiming ground fit.",
            "Door-pocket end caps reach x=+/-96 while the low foundation is x=+/-94; native edge adjacency is tested separately.",
            "No separate damage meshes, reclaimable wreck or upgrade state. Runtime work lamp has no baked emission.",
            "M1A1 normal forward production/exit fits; unrestricted in-bay gun elevation and arbitrary hull yaw do not fit this workshop.",
            "GLB has static closed doors and rigid pieces, not baked motion. Offline poses are inspection copies only.",
            "Existing S3O exporter is reused but its tank sphere is replaced using the full continuous factory motion envelope."],
        source_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
    (PREVIEWS/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(f"Built Vehicle Factory: {manifest['triangles']} instance triangles / {manifest['vertices']} vertices / {manifest['nodes']} nodes", flush=True)
    print(f"Static checks: {len(checks)+len(spaces)-len(failures)} PASS, {len(failures)} FAIL; native validation NOT_RUN", flush=True)
    print("Manifest:", str(PREVIEWS/"manifest.json"), flush=True)
    if failures:
        for row in failures:
            print(json.dumps(row, ensure_ascii=True), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
