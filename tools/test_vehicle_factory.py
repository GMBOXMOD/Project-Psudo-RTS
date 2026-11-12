"""Read-only acceptance tests for the Vehicle Factory's actual delivered assets.

Run AFTER the generator's outputs have been frozen, from any working directory::

    python -I -B D:/Recoil/games/MyGame.sdd/tools/test_vehicle_factory.py -v
    python -I -B D:/Recoil/games/MyGame.sdd/tools/test_vehicle_factory.py --lua-path <existing-lupa-directory> -v

The default checks need only NumPy/Pillow (already used by the asset tools).
Lua tables and the simple UnitDef wrapper are parsed without executing Lua;
--lua-path additionally checks their meaning with the existing lupa.lua51.
Nothing is exported, rendered, installed, or run in the engine. Source meshes
are constructed only in memory. Each input file is read once per test process.

These are acceptance tests, not a G1-only green checklist: gray/palette-study
outputs, stale exports, old Factory1 references, and missing final material
work must fail. The latest production catalogue contains SIX products. The
historical R40 proxy covers only spider/stumpy/flare/duron, never scout/M1A1.
M1A1 idle straight exit and unrestricted gun/yaw clearance are separate tests.
The default --scope all retains the unrestricted-combat diagnostic (currently
FAIL). --scope production explicitly selects the workshop's production/exit
contract; it does not certify arbitrary in-bay combat poses or suppress that
separately runnable diagnostic.

Geometry tests cannot certify G2 visual quality or G4 native production,
pathfinding, terrain tilt, rally/congestion/adjacency, or script scheduling.
Collision dimensions/centre are checked against the midpoint-relative contract
established by the separate native boundary probe, not an engine run here.
"""

from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import importlib
import io
import itertools
import json
import math
from pathlib import Path
import re
import struct
import sys
import unittest

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from test_ztz99a import read_accessor

DATA_PATH = ROOT / "Scripts/vehicle_factory_data.lua"
MANIFEST_PATH = TOOLS / "previews/vehicle_factory/manifest.json"
CATALOGUE = ("spider", "stumpy", "flare", "duron", "scout", "m1a1")
PARENTS = {
    "Base": None, "DoorL": "Base", "DoorR": "Base", "Gantry": "Base",
    "HeadL": "Gantry", "HeadR": "Gantry", "NanoL": "HeadL", "NanoR": "HeadR",
    "FanL": "Base", "FanR": "Base", "WorkLamp": "Base", "BuildSpot": "Base",
}
LOCATORS = {"NanoL", "NanoR", "BuildSpot"}
TEXTURES = ("vehicle_factory_diffuse.tga", "vehicle_factory_material.tga")
EPS = 1e-5
LUA_PATH = None
SUITE_SCOPE = "all"
INPUT_STAMPS = {}

# Independent measurement provenance (not required on other machines):
# C:/Users/Administrator/AppData/Local/Temp/mygame-factory-baseline-_miw1kgg/debug/product_space_report.json
# These rounded baseline values are NOT assertions about a running game pose.
# The native files are pinned; geometry below independently re-derives the bounds.
BASELINE = {
    "spider": (38.086350, 0.0, 23.786963,
        "a7201d5030427830e385acdadbec6c4f484d2644f25acb16ab5a130f11bde82f"),
    "stumpy": (16.281585, -0.65, 29.182082,
        "726502452d2b9f4155b9bd84a68b0c88d8b5ce9dca31426bc772a546a15ceb25"),
    "flare": (28.504386, -1.0, 28.367534,
        "0e42545931add93150a9d83e841e5ad5b79bcad5bd0f9cc031ae0d539707f5a6"),
    "duron": (30.372247, -1.344, 45.136890,
        "bc9e310bc5627b9b81a5f155beecbf11b549b0d173eb516eed66c25a32e111b6"),
}
NATIVE_NAMES = {"stumpy": "Stumpy", "flare": "Flare", "duron": "Duron"}


def require(condition, message):
    """Keep parser/geometry checks active even if Python is invoked with -O."""
    if not condition:
        raise AssertionError(message)


@lru_cache(maxsize=None)
def contents(path):
    path = Path(path).resolve()
    require(path.is_file(), f"Required delivery is missing: {path}")
    before = path.stat()
    result = path.read_bytes()
    after = path.stat()
    stamp = (after.st_size, after.st_mtime_ns)
    require(stamp == (before.st_size, before.st_mtime_ns),
            f"Input changed during reading; freeze outputs before testing: {path}")
    INPUT_STAMPS[path] = stamp
    return result


def text(path):
    return contents(path).decode("utf-8-sig")


# This deliberately accepts only literal tables, not general Lua expressions.
# Long strings/comments are tokenised before punctuation; comments cannot make
# a dead ObjectName or a commented-out build option pass the integration tests.
TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<comment>--\[(?P<ceq>=*)\[.*?\](?P=ceq)\]|--[^\n]*)|"
    r"(?P<long>\[(?P<eq>=*)\[.*?\](?P=eq)\])|"
    r'''(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|'''
    r"(?P<number>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<identifier>[A-Za-z_]\w*)|(?P<punct>.)", re.S)


def decode_string(raw):
    if raw.startswith("["):
        opener = re.match(r"\[(=*)\[", raw)[0]
        value = raw[len(opener):-len(opener)]
        return value[1:] if value.startswith("\n") else value
    result, i = [], 1
    escapes = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
               "t": "\t", "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
    while i < len(raw) - 1:
        if raw[i] != "\\":
            result.append(raw[i])
            i += 1
            continue
        i += 1
        if raw[i].isdigit():
            match = re.match(r"\d{1,3}", raw[i:])[0]
            require(int(match) <= 255, "Lua decimal escape exceeds one byte")
            result.append(chr(int(match)))
            i += len(match)
        else:
            require(raw[i] in escapes, f"Unsupported Lua 5.1 string escape: {raw[i]}")
            result.append(escapes[raw[i]])
            i += 1
    return "".join(result)


def tokens(source):
    result = []
    for match in TOKEN.finditer(source):
        kind, raw = match.lastgroup, match[0]
        if kind in ("space", "comment"):
            continue
        if kind in ("string", "long"):
            result.append(("string", decode_string(raw)))
        else:
            result.append((kind, raw))
    return result


class LiteralLua:
    def __init__(self, source):
        self.tokens = tokens(source)
        self.index = 0

    def peek(self, distance=0):
        i = self.index + distance
        return self.tokens[i][1] if i < len(self.tokens) else None

    def take(self, expected=None):
        require(self.index < len(self.tokens), f"Unexpected end of Lua; expected {expected!r}")
        token = self.tokens[self.index]
        self.index += 1
        require(expected is None or token[1] == expected,
                f"Expected {expected!r}, found {token!r}; only literal Lua is accepted")
        return token

    def value(self):
        kind, value = self.take()
        if kind == "string":
            return value
        if kind == "number":
            number = float(value)
            require(math.isfinite(number), "Non-finite Lua parameter")
            return int(value) if re.fullmatch(r"-?\d+", value) else number
        if value in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[value]
        require(value == "{", f"Not a literal Lua value: {value!r}")
        named, array = {}, []
        while self.peek() != "}":
            if self.peek() == "[":
                self.take("[")
                key = self.value()
                require(isinstance(key, (str, int)) and not isinstance(key, bool), "Invalid literal table key")
                self.take("]")
                self.take("=")
            elif self.peek(1) == "=":
                key_kind, key = self.take()
                require(key_kind == "identifier", "Expected named table field")
                self.take("=")
            else:
                require(not named, "Mixed Lua tables are outside the data contract")
                array.append(self.value())
                key = None
            if key is not None:
                require(not array and key not in named, f"Mixed/duplicate Lua field: {key}")
                named[key] = self.value()
            if self.peek() in (",", ";"):
                self.take()
            else:
                require(self.peek() == "}", "Expected a literal table separator")
        self.take("}")
        return array if array else named

    def finish(self):
        if self.peek() == ";":
            self.take(";")
        require(self.index == len(self.tokens), "Unexpected executable Lua after literal contract")


def lua_data(source):
    parser = LiteralLua(source)
    parser.take("return")
    result = parser.value()
    parser.finish()
    require(isinstance(result, dict), "Data must return a named literal table")
    return result


def unit_definition(source):
    """Validate the *whole* simple local-name/local-table/return-lowerkeys file."""
    parser = LiteralLua(source)
    parser.take("local")
    name_kind, name_var = parser.take()
    require(name_kind == "identifier", "UnitDef local name must be an identifier")
    parser.take("=")
    name = parser.value()
    parser.take("local")
    def_kind, def_var = parser.take()
    require(def_kind == "identifier", "UnitDef local table must be an identifier")
    parser.take("=")
    definition = parser.value()
    for token in ("return", "lowerkeys", "(", "{", "[", name_var, "]", "=", def_var):
        parser.take(token)
    if parser.peek() == ",":
        parser.take(",")
    for token in ("}", ")"):
        parser.take(token)
    parser.finish()
    require(isinstance(name, str) and isinstance(definition, dict), "Malformed UnitDef")
    lowered = {}
    for key, value in definition.items():
        key = key.lower()
        require(key not in lowered or lowered[key] == value,
                f"Conflicting case-insensitive UnitDef field: {key}")
        lowered[key] = value
    return name.lower(), lowered


@lru_cache(maxsize=None)
def parameters():
    return lua_data(text(DATA_PATH))


@lru_cache(maxsize=None)
def manifest():
    return json.loads(text(MANIFEST_PATH))


@lru_cache(maxsize=None)
def factory_definition():
    return unit_definition(text(ROOT / "Units/Factory.lua"))


def parse_s3o(data, legacy=False):
    """Local reader: legacy EMPTY primitive=2/texture2=0 only, no shared patch."""
    require(len(data) >= 52, "Truncated S3O header")
    header = struct.unpack_from("<12si5f4i", data)
    require(header[:2] == (b"Spring unit\0", 0), "Invalid S3O signature/version")
    require(np.isfinite(header[2:7]).all(), "Non-finite S3O header")

    def region(offset, count, size, label):
        require(isinstance(offset, int) and count >= 0 and offset >= 0,
                f"Negative S3O {label} offset/count")
        require(offset + count * size <= len(data), f"S3O {label} exceeds file")
        require(not count or offset >= 52, f"S3O {label} aliases header")

    def string(offset, optional=False):
        if optional and offset == 0:
            return None
        require(52 <= offset < len(data), "S3O string offset outside file")
        end = data.find(b"\0", offset)
        require(end >= offset, "Unterminated S3O string")
        return data[offset:end].decode("utf-8")

    pieces, visited = {}, set()

    def visit(offset, parent):
        region(offset, 1, 52, "piece")
        require(offset not in visited, "S3O cycle/shared piece offset")
        visited.add(offset)
        r = struct.unpack_from("<10i3f", data, offset)
        name_offset, children, child_table, count, vertex_offset, vertex_type, primitive, ni, index_offset, _ = r[:10]
        for off, length, stride, label in ((child_table, children, 4, "children"),
                (vertex_offset, count, 32, "vertices"), (index_offset, ni, 4, "indices")):
            region(off, length, stride, label)
        require(vertex_type == 0, "Unsupported S3O vertex type")
        require(primitive == 0 or (legacy and primitive == 2 and count == ni == 0),
                "Non-triangle S3O geometry (legacy exception is EMPTY nodes only)")
        require(ni % 3 == 0 and bool(count) == bool(ni), "Invalid S3O triangle count")
        name = string(name_offset)
        require(name and name not in pieces, f"Duplicate/empty S3O piece name: {name}")
        vertices = np.frombuffer(data, "<f4", count * 8, vertex_offset).reshape(-1, 8)
        indices = np.frombuffer(data, "<i4", ni, index_offset).reshape(-1, 3)
        pieces[name] = dict(parent=parent, offset=np.asarray(r[-3:]),
                            vertices=vertices, indices=indices)
        for i in range(children):
            visit(struct.unpack_from("<i", data, child_table + i * 4)[0], name)
    visit(header[-4], None)
    return header, pieces, (string(header[-2]), string(header[-1], optional=legacy))


@lru_cache(maxsize=None)
def native(name="vehicle_factory"):
    path = ROOT / "Objects3d" / (NATIVE_NAMES.get(name, name) + ".s3o")
    return parse_s3o(contents(path), legacy=name != "vehicle_factory")


@lru_cache(maxsize=None)
def exchange():
    data = contents(ROOT / "Objects3d/vehicle_factory.glb")
    require(len(data) >= 28, "Truncated GLB")
    require(struct.unpack_from("<III", data) == (0x46546C67, 2, len(data)), "Invalid GLB header")
    size, kind = struct.unpack_from("<II", data, 12)
    require(kind == 0x4E4F534A and size % 4 == 0 and 28 + size <= len(data), "Invalid GLB JSON chunk")
    doc = json.loads(data[20:20 + size])
    binary_size, binary_kind = struct.unpack_from("<II", data, 20 + size)
    require(binary_kind == 0x004E4942 and binary_size % 4 == 0,
            "Invalid GLB BIN chunk")
    require(28 + size + binary_size == len(data), "Truncated/trailing GLB chunks")
    binary = data[28 + size:]
    require(len(doc["buffers"]) == 1 and "uri" not in doc["buffers"][0], "GLB must embed its buffer")
    declared = doc["buffers"][0]["byteLength"]
    require(0 <= len(binary) - declared <= 3, "GLB buffer length/padding mismatch")
    for view in doc["bufferViews"]:
        start, length = view.get("byteOffset", 0), view["byteLength"]
        require(view["buffer"] == 0 and start >= 0 and start % 4 == 0 and length >= 0,
                "Invalid GLB buffer view")
        require(start + length <= declared, "GLB view exceeds declared buffer")
    for accessor in doc["accessors"]:
        require(accessor["componentType"] in (5126, 5125), "Unexpected factory accessor component type")
        require(accessor["type"] in ("SCALAR", "VEC2", "VEC3"), "Unexpected factory accessor type")
        require(not accessor.get("normalized", False) and "sparse" not in accessor,
                "Unexpected normalized/sparse accessor")
        require(isinstance(accessor["bufferView"], int) and 0 <= accessor["bufferView"] < len(doc["bufferViews"]),
                "Invalid accessor buffer-view index")
        view = doc["bufferViews"][accessor["bufferView"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[accessor["type"]]
        offset, count = accessor.get("byteOffset", 0), accessor["count"]
        require("byteStride" not in view and offset >= 0 and offset % 4 == 0 and count > 0,
                "Invalid/interleaved factory accessor")
        require(offset + count * width * 4 <= view["byteLength"], "Accessor spills out of its own view")
    return doc, binary


@lru_cache(maxsize=None)
def source():
    contents(TOOLS / "build_vehicle_factory.py")
    builder = importlib.import_module("build_vehicle_factory")
    root = builder.make_model()  # Pure in-memory geometry, never builder.main().
    pieces, seen = {}, set()

    def visit(piece, parent):
        require(id(piece) not in seen and piece.name not in pieces, "Repeated source node/cycle")
        seen.add(id(piece))
        mesh = piece.mesh
        vertices = np.column_stack((mesh.positions, mesh.normals, mesh.uvs)) if mesh is not None else np.empty((0, 8))
        indices = np.asarray(mesh.indices) if mesh is not None else np.empty(0, dtype=int)
        require(indices.dtype.kind in "iu" and indices.size % 3 == 0, "Non-integer source indices")
        pieces[piece.name] = dict(parent=parent, offset=np.asarray(piece.offset, dtype=float),
            vertices=vertices, indices=indices.reshape(-1, 3), mesh_name=mesh.name if mesh is not None else None,
            mesh=mesh, components=list(getattr(mesh, "components", ())))
        for child in piece.children:
            visit(child, piece.name)
    visit(root, None)
    return builder, root, pieces


@lru_cache(maxsize=None)
def glb_pieces():
    doc, binary = exchange()
    parents, pieces = {}, {}
    nodes = doc["nodes"]
    for node in nodes:
        for child in node.get("children", []):
            require(isinstance(child, int) and 0 <= child < len(nodes) and child not in parents,
                    "Invalid/shared GLB child")
            parents[child] = node["name"]
    for i, node in enumerate(nodes):
        name = node["name"]
        require(name not in pieces, f"Duplicate GLB node name: {name}")
        require(not {"matrix", "rotation", "scale", "skin"}.intersection(node),
                "Rest transforms must agree with translation-only S3O pieces")
        record = dict(parent=parents.get(i), offset=np.asarray(node.get("translation", (0, 0, 0))),
                      vertices=np.empty((0, 8)), indices=np.empty((0, 3), dtype=int), mesh_name=None)
        if "mesh" in node:
            require(isinstance(node["mesh"], int) and 0 <= node["mesh"] < len(doc["meshes"]), "Invalid GLB mesh index")
            mesh = doc["meshes"][node["mesh"]]
            require(len(mesh["primitives"]) == 1, "Count/validate every primitive; factory contract is one per mesh")
            primitive = mesh["primitives"][0]
            require(primitive.get("mode", 4) == 4 and primitive.get("material") == 0, "Not single-material triangles")
            require(set(primitive["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0"}, "Unexpected/missing vertex attributes")
            for index in [primitive["indices"], *primitive["attributes"].values()]:
                require(isinstance(index, int) and 0 <= index < len(doc["accessors"]), "Invalid GLB accessor index")
            arrays = [read_accessor(doc, binary, primitive["attributes"][key])
                      for key in ("POSITION", "NORMAL", "TEXCOORD_0")]
            for key in ("POSITION", "NORMAL", "TEXCOORD_0"):
                require(doc["accessors"][primitive["attributes"][key]]["componentType"] == 5126,
                        "Geometry attributes must be floating point")
                if key != "TEXCOORD_0":
                    accessor = doc["accessors"][primitive["attributes"][key]]
                    decoded = arrays[0 if key == "POSITION" else 1]
                    np.testing.assert_allclose(accessor["min"], decoded.min(axis=0), rtol=0, atol=EPS)
                    np.testing.assert_allclose(accessor["max"], decoded.max(axis=0), rtol=0, atol=EPS)
            require(doc["accessors"][primitive["indices"]]["componentType"] == 5125,
                    "Indices must be unsigned integers")
            record.update(vertices=np.column_stack(arrays),
                indices=read_accessor(doc, binary, primitive["indices"]).reshape(-1, 3),
                mesh_name=mesh["name"], mesh_id=node["mesh"])
        pieces[name] = record
    return pieces


def ancestors(pieces, name):
    seen = set()
    while name is not None:
        require(name in pieces and name not in seen, f"Broken piece parent chain: {name}")
        seen.add(name)
        yield name
        name = pieces[name]["parent"]


def origin(pieces, name):
    return sum((pieces[key]["offset"] for key in ancestors(pieces, name)), np.zeros(3))


def world_vertices(pieces, name):
    return pieces[name]["vertices"][:, :3].astype(float) + origin(pieces, name)


def xyz(value):
    return np.asarray([value[key] for key in ("x", "y", "z")], dtype=float)


def corners(low, high):
    return np.asarray(list(itertools.product(*zip(low, high))), dtype=float)


def motion_ranges(data):
    d, g, h = data["door"], data["gantry"], data["heads"]
    return {
        "DoorL": ((d["leftOpenMoveWorld"], 0, 0), (d["closedMoveWorld"], 0, 0)),
        "DoorR": ((d["closedMoveWorld"], 0, 0), (d["rightOpenMoveWorld"], 0, 0)),
        "Gantry": ((0, 0, g["minMoveWorld"]), (0, 0, g["maxMoveWorld"])),
        "HeadL": ((h["minXMoveWorld"], h["minYMoveWorld"], 0), (h["maxXMoveWorld"], h["maxYMoveWorld"], 0)),
        "HeadR": ((h["minXMoveWorld"], h["minYMoveWorld"], 0), (h["maxXMoveWorld"], h["maxYMoveWorld"], 0)),
    }


def translation_interval(pieces, name, data):
    ranges = motion_ranges(data)
    low, high = origin(pieces, name), origin(pieces, name)
    for key in ancestors(pieces, name):
        if key in ranges:
            a, b = np.asarray(ranges[key], dtype=float)
            require(np.all(a <= b), f"Inverted motion range: {key}")
            low, high = low + a, high + b
    return low, high


def motion_bounds(pieces, data):
    """Independent interval proof; no generator sweep/pose/validation calls."""
    result = {}
    for name, piece in pieces.items():
        low, high = translation_interval(pieces, name, data)
        v = piece["vertices"][:, :3]
        if len(v):
            a, b = v.min(axis=0), v.max(axis=0)
            if name in ("FanL", "FanR"):
                require(data["fans"]["axis"] == "y" and data["fans"]["fullContinuousRotation"], "Unknown fan motion")
                radius = np.hypot(v[:, 0], v[:, 2]).max()
                a[[0, 2]], b[[0, 2]] = -radius, radius
            low, high = low + a, high + b
        result[name] = (low, high)
    visible = [result[name] for name, piece in pieces.items() if len(piece["vertices"])]
    return result, (np.min([a for a, _ in visible], axis=0), np.max([b for _, b in visible], axis=0))


def state_vertices(pieces, data, door=0, gantry=0, heads=None, fans=None):
    moves = {"DoorL": np.array((data["door"]["leftOpenMoveWorld"] * door, 0, 0)),
             "DoorR": np.array((data["door"]["rightOpenMoveWorld"] * door, 0, 0)),
             "Gantry": np.array((0, 0, gantry))}
    moves.update(heads or {})
    for name, piece in pieces.items():
        v = piece["vertices"][:, :3].astype(float)
        if not len(v):
            continue
        angle = (fans or {}).get(name, 0)
        if angle:
            c, s = math.cos(angle), math.sin(angle)
            v = v @ np.array(((c, 0, s), (0, 1, 0), (-s, 0, c))).T
        position = origin(pieces, name) + sum((moves.get(key, np.zeros(3))
                   for key in ancestors(pieces, name)), np.zeros(3))
        yield name, v + position


def trig_limits(a, b, low, high):
    """Exact min/max of a*cos(t)+b*sin(t), including interior critical angles."""
    require(low <= high, "Reversed angle interval")
    a, b = np.asarray(a), np.asarray(b)
    first, last = a * math.cos(low) + b * math.sin(low), a * math.cos(high) + b * math.sin(high)
    minimum, maximum = np.minimum(first, last), np.maximum(first, last)
    radius, phase = np.hypot(a, b), np.arctan2(b, a)
    peak = phase + np.ceil((low - phase) / math.tau) * math.tau
    trough_phase = phase + math.pi
    trough = trough_phase + np.ceil((low - trough_phase) / math.tau) * math.tau
    return (np.where(trough <= high + 1e-12, -radius, minimum),
            np.where(peak <= high + 1e-12, radius, maximum))


def triangle_box_overlap(triangles, low, high):
    """Triangle/AABB SAT, including planar obstacles; mere touching is allowed."""
    low, high = np.asarray(low) + EPS, np.asarray(high) - EPS
    if not len(triangles) or np.any(high <= low):
        return False
    t = np.asarray(triangles) - (low + high) / 2
    edges = np.roll(t, -1, axis=1) - t
    unit = np.eye(3)
    axes = np.concatenate((np.broadcast_to(unit, (len(t), 3, 3)),
        np.cross(edges[:, 0], edges[:, 1])[:, None, :],
        np.cross(edges[:, :, None, :], unit[None, None, :, :]).reshape(-1, 9, 3)), axis=1)
    projections = np.einsum("nvc,nac->nav", t, axes)
    radii = np.einsum("nac,c->na", np.abs(axes), (high - low) / 2)
    separated = (projections.min(axis=2) > radii) | (projections.max(axis=2) < -radii)
    return bool(np.any(~np.any(separated, axis=1)))


def closed_surface(triangles):
    edges = Counter()
    for tri in np.round(triangles, 7):
        points = [tuple(point) for point in tri]
        for i in range(3):
            edges[tuple(sorted((points[i], points[(i + 1) % 3])))] += 1
    return bool(edges) and all(count == 2 for count in edges.values())


def point_in_closed_surface(point, triangles):
    # Winding solid angle also respects holes; it does not fill a ring's AABB.
    a, b, c = np.moveaxis(np.asarray(triangles) - point, 1, 0)
    la, lb, lc = (np.linalg.norm(v, axis=1) for v in (a, b, c))
    denominator = la * lb * lc + np.sum(a * b, axis=1) * lc + np.sum(b * c, axis=1) * la + np.sum(c * a, axis=1) * lb
    numerator = np.einsum("ij,ij->i", a, np.cross(b, c))
    return abs(float(np.sum(2 * np.arctan2(numerator, denominator)))) > 2 * math.pi


@lru_cache(maxsize=None)
def components():
    """Recompute every component bound from its indexed triangles, not metadata."""
    pieces = source()[2]
    result = {}
    for name, piece in pieces.items():
        if not len(piece["vertices"]):
            continue
        nv, ni = len(piece["vertices"]), piece["indices"].size
        vertex_coverage, index_coverage = np.zeros(nv, int), np.zeros(ni, int)
        names = set()
        result[name] = []
        for component in piece["components"]:
            label = component["name"]
            require(label not in names, f"Duplicate component: {name}/{label}")
            names.add(label)
            a, count = component["vertex_start"], component["vertex_count"]
            b, length = component["index_start"], component["index_count"]
            require(0 <= a < a + count <= nv and 0 <= b < b + length <= ni,
                    f"Component range outside mesh: {name}/{label}")
            require(b % 3 == length % 3 == 0, f"Component splits a triangle: {label}")
            ix = piece["indices"].ravel()[b:b + length]
            require(ix.min() >= a and ix.max() < a + count, f"Component uses another component's vertices: {label}")
            vertex_coverage[a:a + count] += 1
            index_coverage[b:b + length] += 1
            local = piece["vertices"][a:a + count, :3]
            np.testing.assert_allclose(local.min(axis=0), component["min"], rtol=0, atol=EPS)
            np.testing.assert_allclose(local.max(axis=0), component["max"], rtol=0, atol=EPS)
            triangles = world_vertices(pieces, name)[ix.reshape(-1, 3)]
            result[name].append(dict(name=label, role=component["role"], triangles=triangles,
                low=triangles.min(axis=(0, 1)), high=triangles.max(axis=(0, 1)),
                closed=closed_surface(triangles)))
        require(np.all(vertex_coverage == 1) and np.all(index_coverage == 1),
                f"Unclassified/overlapping geometry would invalidate clearance checks: {name}")
    return result


def fixed_hits(low, high):
    """Actual component triangles plus solid containment, NEVER Base's total box."""
    result = []
    for component in components()["Base"]:
        if np.any(np.minimum(high, component["high"]) < np.maximum(low, component["low"])):
            continue
        if triangle_box_overlap(component["triangles"], low, high) or (
                component["closed"] and point_in_closed_surface((np.asarray(low) + high) / 2, component["triangles"])):
            result.append(component["name"])
    return result


def overlaps(a, b):
    return bool(np.all(np.minimum(a[1], b[1]) - np.maximum(a[0], b[0]) > EPS))


def component_named(piece, name):
    matches = [row for row in components()[piece] if row["name"] == name]
    require(len(matches) == 1, f"Expected one geometry component: {piece}/{name}")
    return matches[0]


def polygon_area(points):
    if len(points) < 3:
        return 0.0
    p = np.asarray(points)
    return abs(float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1)))) / 2


def clip_polygon(points, clip):
    """Convex polygon intersection for continuous floor-coverage area checks."""
    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]
    clip = np.asarray(clip)
    signed = sum(cross(clip[i], clip[(i + 1) % len(clip)]) for i in range(len(clip)))
    sense = 1 if signed >= 0 else -1
    out = [np.asarray(point) for point in points]
    for a, b in zip(clip, np.roll(clip, -1, axis=0)):
        old, out = out, []
        if not old:
            break
        previous = old[-1]
        dp = sense * cross(b - a, previous - a)
        for current in old:
            dc = sense * cross(b - a, current - a)
            if (dp >= 0) != (dc >= 0):
                out.append(previous + (current - previous) * dp / (dp - dc))
            if dc >= 0:
                out.append(current)
            previous, dp = current, dc
    return out


def aggregate_envelopes(rows):
    return dict(low=np.min([r[0] for r in rows], axis=0), high=np.max([r[1] for r in rows], axis=0),
                radius=max(r[2] for r in rows))


def static_envelope(pieces):
    points = np.concatenate([world_vertices(pieces, name) for name, p in pieces.items() if len(p["vertices"])])
    return dict(low=points.min(axis=0), high=points.max(axis=0), radius=np.hypot(points[:, 0], points[:, 2]).max())


def scripted_angle_range(piece_name):
    """Read the SP6's actual literal X-turn goals, including its zero rest pose."""
    values = tokens(text(ROOT / "Scripts/spiderscript.lua"))
    goals = []
    for i in range(len(values) - 7):
        if [value for _, value in values[i:i + 4]] != ["Turn", "(", piece_name, ","]:
            continue
        require([value for _, value in values[i + 4:i + 6]] == ["x_axis", ","],
                f"Unmodelled SP6 arm turn axis: {piece_name}")
        kind, value = values[i + 6]
        if kind == "number":
            require(values[i + 7][1] == ",", "Non-literal SP6 turn goal")
            goals.append(float(value))
        else:
            expression = values[i + 6:i + 13]
            require(len(expression) == 7 and [v for _, v in expression[:4]] == ["math", ".", "rad", "("]
                    and expression[4][0] == "number" and [v for _, v in expression[5:]] == [")", ","],
                    f"SP6 arm goal needs new analysis: {piece_name}")
            goals.append(math.radians(float(expression[4][1])))
    require(goals, f"No SP6 angle goals found for {piece_name}")
    return min(goals), max(goals)


def scripted_recoil_range(name, gun):
    """Move goals are parent-local deltas, not baked into gun-local vertices."""
    basename = NATIVE_NAMES.get(name, name)
    values = tokens(text(ROOT / "Scripts" / (basename + "script.lua")))
    goals = [0.0]
    for i in range(len(values) - 7):
        if [value for _, value in values[i:i + 4]] != ["Move", "(", gun, ","]:
            continue
        require([value for _, value in values[i + 4:i + 6]] == ["z_axis", ","],
                f"Unmodelled {name} gun translation axis")
        require(values[i + 6][0] == "number" and values[i + 7][1] == ",",
                f"Non-literal {name} recoil needs new analysis")
        goals.append(float(values[i + 6][1]))
    return min(goals), max(goals)


def spider_envelope(pieces, idle=False):
    """Native canonical legs + real rig yaw, with continuous independent knees."""
    rig = lua_data(text(ROOT / "Scripts/spider_rig_data.lua"))
    rows, moving = [], set()
    amplitude, lift = (0, 0) if idle else (rig["hipAmplitude"], rig["kneeLift"])
    for leg in rig["legs"]:
        hip, knee = leg["hip"], leg["knee"]
        require(pieces[knee]["parent"] == hip, "SP6 knee parent changed; re-measure its rig")
        pivot = origin(pieces, hip)
        lo, hi = leg["yaw"] - amplitude, leg["yaw"] + amplitude
        for name in (hip, knee):
            moving.add(name)
            v = pieces[name]["vertices"][:, :3].astype(float)
            if name == hip:
                qx0 = qx1 = v[:, 0]
                qz, y0, y1 = v[:, 2], v[:, 1], v[:, 1]
            else:
                offset = pieces[knee]["offset"]
                qx0, qx1 = trig_limits(v[:, 0], -v[:, 1], 0, lift)
                qx0, qx1 = qx0 + offset[0], qx1 + offset[0]
                qz = v[:, 2] + offset[2]
                y0, y1 = trig_limits(v[:, 1], v[:, 0], 0, lift)
                y0, y1 = y0 + offset[1], y1 + offset[1]
            x0, x1 = trig_limits(qx0, qz, lo, hi)
            xa, xb = trig_limits(qx1, qz, lo, hi)
            z0, z1 = trig_limits(qz, -qx0, lo, hi)
            za, zb = trig_limits(qz, -qx1, lo, hi)
            low = np.array((np.minimum(x0, xa).min(), y0.min(), np.minimum(z0, za).min())) + pivot
            high = np.array((np.maximum(x1, xb).max(), y1.max(), np.maximum(z1, zb).max())) + pivot
            radius = np.hypot(pivot[0], pivot[2]) + np.hypot(np.maximum(abs(qx0), abs(qx1)), qz).max()
            rows.append((low, high, radius))
    for side in ("L", "R"):
        arm, fore = "Arm" + side, "Forearm" + side
        pivot = origin(pieces, arm)
        for name in (arm, fore):
            moving.add(name)
            v = pieces[name]["vertices"][:, :3].astype(float)
            amin, amax = (0, 0) if idle else scripted_angle_range(arm)
            bmin, bmax = (0, 0) if idle or name == arm else scripted_angle_range(fore)
            y0, y1 = trig_limits(v[:, 1], -v[:, 2], amin + bmin, amax + bmax)
            z0, z1 = trig_limits(v[:, 2], v[:, 1], amin + bmin, amax + bmax)
            offset = np.zeros(3) if name == arm else pieces[fore]["offset"]
            oy0, oy1 = trig_limits(offset[1], -offset[2], amin, amax)
            oz0, oz1 = trig_limits(offset[2], offset[1], amin, amax)
            low = pivot + (v[:, 0].min() + offset[0], y0.min() + oy0, z0.min() + oz0)
            high = pivot + (v[:, 0].max() + offset[0], y1.max() + oy1, z1.max() + oz1)
            radius = max(np.hypot(p[0], p[2]) for p in corners(low, high))
            rows.append((low, high, radius))
    for name, p in pieces.items():
        if name not in moving and len(p["vertices"]):
            points = world_vertices(pieces, name)
            rows.append((points.min(axis=0), points.max(axis=0), np.hypot(points[:, 0], points[:, 2]).max()))
    return aggregate_envelopes(rows)


def vehicle_envelope(name, pieces):
    """Full turret yaw, un-clamped script pitch, recoil and wheel/track motion.

    This is a conservative flat-ground proxy, NOT measured engine aiming limits.
    The endpoint/stationary-angle formulas operate on all native vertices.
    """
    gun = "Gun" if name in ("scout", "m1a1") else "TurretMuzzle"
    require(pieces[gun]["parent"] == "Turret", f"Unexpected {name} gun hierarchy")
    pivot, offset = origin(pieces, "Turret"), pieces[gun]["offset"]
    recoil_low, recoil_high = scripted_recoil_range(name, gun)
    rows = []
    track = lua_data(text(ROOT / "Scripts/m1a1_track_data.lua")) if name == "m1a1" else None
    for label, piece in pieces.items():
        v = piece["vertices"][:, :3].astype(float)
        if not len(v):
            continue
        chain = list(ancestors(pieces, label))
        if gun in chain:
            # Descendant offsets remain in the gun-local frame; recoil is a
            # parent-local translation, not a change to baked vertex positions.
            local = v + origin(pieces, label) - origin(pieces, gun)
            r = np.hypot(local[:, 1], local[:, 2])
            radial = np.sqrt((local[:, 0] + offset[0]) ** 2 +
                (r + max(abs(offset[2] + recoil_low), abs(offset[2] + recoil_high))) ** 2).max()
            low = pivot + (-radial, offset[1] - r.max(), -radial)
            high = pivot + (radial, offset[1] + r.max(), radial)
            radius = np.hypot(pivot[0], pivot[2]) + radial
        elif "Turret" in chain:
            local = v + origin(pieces, label) - pivot
            r = np.hypot(local[:, 0], local[:, 2]).max()
            low, high = pivot + (-r, local[:, 1].min(), -r), pivot + (r, local[:, 1].max(), r)
            radius = np.hypot(pivot[0], pivot[2]) + r
        elif label.startswith(("Wheel", "Idler")):
            centre = origin(pieces, label)
            r = np.hypot(v[:, 1], v[:, 2])
            low = centre + (v[:, 0].min(), -r.max(), -r.max())
            high = centre + (v[:, 0].max(), r.max(), r.max())
            radius = np.hypot(v[:, 0] + centre[0], abs(centre[2]) + r).max()
        elif label.startswith("Track") and track is not None:
            # Closed path extrema + each shoe's complete baked-X rotation disc.
            r = np.hypot(v[:, 1], v[:, 2]).max()
            x = origin(pieces, label)[0]
            low = np.array((x + v[:, 0].min(), track["centerY"] - track["radius"] - r,
                            -track["halfStraight"] - track["radius"] - r))
            high = np.array((x + v[:, 0].max(), track["centerY"] + track["radius"] + r,
                             track["halfStraight"] + track["radius"] + r))
            radius = max(np.hypot(p[0], p[2]) for p in corners(low, high))
        else:
            points = world_vertices(pieces, label)
            low, high = points.min(axis=0), points.max(axis=0)
            radius = np.hypot(points[:, 0], points[:, 2]).max()
        rows.append((low, high, radius))
    return aggregate_envelopes(rows)


@lru_cache(maxsize=None)
def product_envelope(name, idle=False):
    pieces = native(name)[1]
    if name == "spider":
        return spider_envelope(pieces, idle)
    return static_envelope(pieces) if idle else vehicle_envelope(name, pieces)


def exit_check(envelope, rotating_body=True):
    data, pieces = parameters(), source()[2]
    start = origin(pieces, "BuildSpot")
    floor = data["foundation"]["driveFloorYWorld"]
    if rotating_body:
        radius = float(envelope["radius"]) + 0.001
        low = np.array((-radius, envelope["low"][1], -radius))
        high = np.array((radius, envelope["high"][1], radius))
    else:
        low, high = np.array(envelope["low"]), np.array(envelope["high"])
    end_z = data["corridor"]["apronFrontZWorld"] - low[2] + 4
    path_low, path_high = low + start, high + (start[0], start[1], end_z)
    # Legacy wheel/track sub-ground tails are inherited grounding offsets, not a
    # reason to edit or raise products. The floor check handles that boundary.
    path_low[1] = max(path_low[1], floor + 2 * EPS)
    hits = fixed_hits(path_low, path_high)
    sweep, _ = motion_bounds(pieces, data)
    for label in ("Gantry", "HeadL", "HeadR"):
        if overlaps((path_low, path_high), sweep[label]):
            hits.append(label + " full travel")
    opened = dict(state_vertices(pieces, data, door=1))
    for label in ("DoorL", "DoorR"):
        if overlaps((path_low, path_high), (opened[label].min(axis=0), opened[label].max(axis=0))):
            hits.append(label + " fully open")
    corridor = data["corridor"]
    margins = dict(left=path_low[0] - corridor["minXWorld"],
        right=corridor["maxXWorld"] - path_high[0],
        rear=path_low[2] - corridor["rearInnerZWorld"],
        lintel=corridor["lintelBottomYWorld"] - path_high[1],
        tool=min(sweep[label][0][1] for label in ("HeadL", "HeadR")) - path_high[1])
    return hits, margins, (path_low, path_high)


@lru_cache(maxsize=None)
def image(path):
    result = Image.open(io.BytesIO(contents(path)))
    result.load()
    return result


def atlas_images():
    return tuple(image(ROOT / "UnitTextures" / name) for name in TEXTURES)


class ReaderAndMathTests(unittest.TestCase):
    def test_literal_parser_ignores_comments_but_rejects_expressions(self):
        self.assertEqual(lua_data('return {a=nil, b={1,-2.5e1}, c=[[x]], -- ignored\n ok=true}'),
                         {"a": None, "b": [1, -25.0], "c": "x", "ok": True})
        for invalid in ('return {a=1,a=2}', 'return {a=2+2}', 'return {a=0/0}', 'return {} print(1)'):
            with self.subTest(source=invalid), self.assertRaises(AssertionError):
                lua_data(invalid)

    def test_local_s3o_reader_accepts_only_empty_legacy_quads(self):
        data = bytearray(104)
        name = len(data)
        data.extend(b"Empty\0")
        tex = len(data)
        data.extend(b"old.tga\0")
        struct.pack_into("<12si5f4i", data, 0, b"Spring unit\0", 0, 1, 1, 0, 0, 0, 52, 0, tex, 0)
        struct.pack_into("<10i3f", data, 52, name, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0)
        self.assertEqual(parse_s3o(bytes(data), legacy=True)[1]["Empty"]["vertices"].shape, (0, 8))
        with self.assertRaises(AssertionError):
            parse_s3o(bytes(data))
        struct.pack_into("<i", data, 52 + 7 * 4, 3)
        with self.assertRaises(AssertionError):
            parse_s3o(bytes(data), legacy=True)

    def test_rotation_extrema_are_not_just_angle_endpoints(self):
        low, high = trig_limits(1, 2, 0, math.pi)
        self.assertAlmostEqual(float(low), -1)
        self.assertAlmostEqual(float(high), math.sqrt(5))
        self.assertAlmostEqual(float(trig_limits(2, 2, 0, math.tau)[1]), math.sqrt(8))

    def test_sphere_uses_eight_mixed_corners(self):
        points = corners((-1, -2, -3), (4, 5, 6))
        self.assertEqual(len(points), 8)
        self.assertAlmostEqual(float(np.linalg.norm(points - (10, -10, 20), axis=1).max()), math.sqrt(875))

    def test_planar_barrier_is_not_lost_by_zero_thickness_aabb(self):
        plane = np.array([[(-2, -2, 0), (2, -2, 0), (0, 2, 0)]], dtype=float)
        self.assertTrue(triangle_box_overlap(plane, (-1, -1, -1), (1, 1, 1)))
        self.assertFalse(triangle_box_overlap(plane, (4, 4, 4), (5, 5, 5)))


class FactoryGeometryTests(unittest.TestCase):
    def test_all_serialized_parameters_match_current_source(self):
        builder, root, _ = source()
        # String generation is side-effect-free. This detects stale *all-field*
        # data; independent geometry/motion tests below are the actual oracle.
        expected = lua_data(builder.parameter_lua(root, builder.sweep_bounds(root)))
        self.assertEqual(parameters(), expected, "Regenerate frozen outputs after source edits; do not hand-edit Lua data")
        self.assertEqual(parameters()["schemaVersion"], 1)

    def test_twelve_node_parent_local_contract_and_empty_locators(self):
        data = parameters()
        stats = data["pieces"]
        self.assertEqual(len(stats), 12)
        self.assertEqual({row["name"] for row in stats}, set(PARENTS))
        declared = {row["name"]: row for row in stats}
        variants = {"source": source()[2], "S3O": native()[1], "GLB": glb_pieces()}
        for variant, pieces in variants.items():
            self.assertEqual(set(pieces), set(PARENTS), variant)
            for name, parent in PARENTS.items():
                with self.subTest(format=variant, piece=name):
                    record = pieces[name]
                    self.assertEqual(record["parent"], parent)
                    self.assertEqual(declared[name].get("parent"), parent)
                    self.assertTrue(np.isfinite(record["offset"]).all())
                    np.testing.assert_allclose(record["offset"], declared[name]["offset_world"], rtol=0, atol=EPS)
                    self.assertEqual(len(record["vertices"]) == 0, name in LOCATORS)
                    if name in LOCATORS:
                        self.assertEqual(record["indices"].size, 0)
                        self.assertIsNone(declared[name].get("mesh"))
                        if variant == "source":
                            self.assertIsNone(record["mesh"], "Locators must be mesh=None, not dummy empty Mesh objects")
                        if variant == "GLB":
                            self.assertNotIn("mesh_id", record)
        pieces = variants["source"]
        np.testing.assert_allclose(origin(pieces, "BuildSpot"), xyz(data["buildSpot"]["positionWorld"]), rtol=0, atol=EPS)
        np.testing.assert_allclose(origin(pieces, "Gantry"), xyz(data["gantry"]["pivotWorld"]), rtol=0, atol=EPS)
        for side, key in (("L", "leftParentOffsetWorld"), ("R", "rightParentOffsetWorld")):
            np.testing.assert_allclose(pieces["Head" + side]["offset"], xyz(data["heads"][key]), rtol=0, atol=EPS)
            np.testing.assert_allclose(pieces["Nano" + side]["offset"], xyz(data["heads"]["nanoLocalOffsetWorld"]), rtol=0, atol=EPS)
        doc, _ = exchange()
        self.assertEqual([doc["nodes"][i]["name"] for i in doc["scenes"][doc["scene"]]["nodes"]], ["Base"])
        self.assertFalse(doc.get("animations"))
        self.assertFalse(doc.get("skins"))

    def test_budget_and_vertices_count_each_visible_instance(self):
        data, report = parameters(), manifest()
        totals = []
        for kind, pieces in (("source", source()[2]), ("S3O", native()[1]), ("GLB", glb_pieces())):
            triangle_count = vertex_count = visible = 0
            declared = {row["name"]: row for row in data["pieces"]}
            for name, piece in pieces.items():
                with self.subTest(format=kind, piece=name):
                    triangles, vertices = len(piece["indices"]), len(piece["vertices"])
                    self.assertEqual((triangles, vertices), (declared[name]["triangles"], declared[name]["vertices"]))
                    triangle_count += triangles
                    vertex_count += vertices
                    visible += bool(vertices)
            self.assertGreater(triangle_count, 0)
            self.assertLessEqual(triangle_count, 6000, "6000 is a review ceiling, no artificial minimum budget")
            self.assertEqual(visible, 9)
            totals.append((triangle_count, vertex_count))
        self.assertEqual(totals, [totals[0]] * 3)
        self.assertEqual(totals[0], (data["totals"]["triangles"], data["totals"]["vertices"]))
        self.assertEqual(totals[0], (report["triangles"], report["vertices"]))
        for key, value in (("nodes", 12), ("meshNodes", 9), ("materialSlots", 1)):
            self.assertEqual(data["totals"][key], value)
        self.assertEqual(report["state_geometry_peak"]["triangles"], totals[0][0])
        self.assertEqual(report["state_geometry_peak"]["vertices"], totals[0][1])
        self.assertEqual(report["piece_statistics"], data["pieces"])
        self.assertEqual(report["source_sha256"], hashlib.sha256(contents(TOOLS / "build_vehicle_factory.py")).hexdigest())

    def test_source_s3o_glb_match_including_output_v_flip(self):
        for name, original in source()[2].items():
            with self.subTest(piece=name):
                s3o, glb = native()[1][name], glb_pieces()[name]
                np.testing.assert_array_equal(s3o["indices"], original["indices"])
                np.testing.assert_array_equal(glb["indices"], original["indices"])
                if name in LOCATORS:
                    continue
                expected = original["vertices"].copy()
                expected[:, 7] = 1 - expected[:, 7]
                np.testing.assert_allclose(s3o["vertices"], expected, rtol=0, atol=EPS)
                # S3O flips V after float32 conversion; GLB flips before casting.
                np.testing.assert_allclose(glb["vertices"], expected, rtol=0, atol=EPS)
                np.testing.assert_allclose(glb["vertices"], s3o["vertices"], rtol=0, atol=1.2e-7)
                np.testing.assert_allclose(world_vertices(native()[1], name), world_vertices(glb_pieces(), name), rtol=0, atol=EPS)

    def test_finite_indices_unit_flat_normals_winding_and_uv(self):
        for kind, pieces in (("source", source()[2]), ("S3O", native()[1]), ("GLB", glb_pieces())):
            for name, p in pieces.items():
                with self.subTest(format=kind, piece=name):
                    v, ix = p["vertices"], p["indices"]
                    if not len(v):
                        continue
                    self.assertTrue(np.isfinite(v).all())
                    self.assertEqual(v.shape[1], 8)
                    self.assertGreater(len(ix), 0)
                    self.assertTrue(ix.dtype.kind in "iu" and ix.min() >= 0 and ix.max() < len(v))
                    self.assertTrue(np.all((v[:, 6:] >= 0) & (v[:, 6:] <= 1)))
                    np.testing.assert_allclose(np.linalg.norm(v[:, 3:6], axis=1), 1, rtol=0, atol=2e-6)
                    tri, normals = v[ix, :3], v[ix, 3:6]
                    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
                    lengths = np.linalg.norm(cross, axis=1)
                    self.assertTrue(np.all(lengths > 1e-7), "Degenerate triangle")
                    np.testing.assert_allclose(normals[:, 0], normals[:, 1], rtol=0, atol=2e-6)
                    np.testing.assert_allclose(normals[:, 0], normals[:, 2], rtol=0, atol=2e-6)
                    np.testing.assert_allclose(cross / lengths[:, None], normals[:, 0], rtol=0, atol=2e-5,
                                               err_msg="Winding/face plane disagrees with stored normal")

    def test_name_deduplication_never_merges_distinct_geometry(self):
        same_names, shared_ids = {}, {}
        doc, _ = exchange()
        mesh_names = [m["name"] for m in doc["meshes"]]
        self.assertEqual(len(mesh_names), len(set(mesh_names)))
        self.assertEqual(set(mesh_names), {p["mesh_name"] for p in source()[2].values() if p["mesh"] is not None},
                         "GLB must not hide unmatched/orphan meshes outside its scene")
        for name, p in source()[2].items():
            if p["mesh"] is None:
                continue
            signature = (p["vertices"].astype("<f8").tobytes(), p["indices"].astype("<i8").tobytes())
            for mapping, key in ((same_names, p["mesh_name"]), (shared_ids, glb_pieces()[name]["mesh_id"])):
                if key in mapping:
                    self.assertEqual(mapping[key], signature, f"Same name/index aliases different geometry at {name}")
                mapping[key] = signature
            self.assertEqual(glb_pieces()[name]["mesh_name"], p["mesh_name"])


class FactoryMotionAndSpaceTests(unittest.TestCase):
    def test_component_ranges_cover_every_triangle_and_vertex(self):
        self.assertEqual(set(components()), set(PARENTS) - LOCATORS)

    def test_data_closed_open_and_continuous_bounds_are_rederived(self):
        data, pieces = parameters(), source()[2]
        for label, door in (("closed", 0), ("opened", 1)):
            points = np.concatenate([v for _, v in state_vertices(pieces, data, door=door)])
            for key, actual in (("min", points.min(axis=0)), ("max", points.max(axis=0)), ("size", np.ptp(points, axis=0))):
                np.testing.assert_allclose(data["bounds"][label][key], actual, rtol=0, atol=EPS)
        per_piece, bounds = motion_bounds(pieces, data)
        declared = data["bounds"]["fullMotion"]
        self.assertEqual(set(declared["pieces"]), set(pieces))
        for name, (low, high) in per_piece.items():
            with self.subTest(piece=name):
                for key, actual in (("min", low), ("max", high), ("size", high - low)):
                    np.testing.assert_allclose(declared["pieces"][name][key], actual, rtol=0, atol=EPS)
        np.testing.assert_allclose(declared["aabb"]["min"], bounds[0], rtol=0, atol=EPS)
        np.testing.assert_allclose(declared["aabb"]["max"], bounds[1], rtol=0, atol=EPS)
        self.assertAlmostEqual(data["fans"]["maxAngleRadians"] - data["fans"]["minAngleRadians"], math.tau)

    def test_native_sphere_and_height_cover_all_eight_corners_and_motion(self):
        header, pieces, _ = native()
        data = parameters()
        _, (low, high) = motion_bounds(pieces, data)
        centre, radius, height = np.asarray(header[4:7]), header[2], header[3]
        self.assertGreater(radius, 0)
        self.assertLessEqual(np.linalg.norm(corners(low, high) - centre, axis=1).max(), radius + EPS)
        self.assertGreaterEqual(height + EPS, high[1])
        declared = data["bounds"]["fullMotion"]
        np.testing.assert_allclose(centre, declared["sphere_center"], rtol=0, atol=EPS)
        self.assertAlmostEqual(radius, declared["sphere_radius"], delta=EPS)
        self.assertAlmostEqual(height, declared["s3o_height"], delta=EPS)
        # Exact per-vertex continuous proof in addition to conservative box corners.
        for name, piece in pieces.items():
            if not len(piece["vertices"]):
                continue
            v = piece["vertices"][:, :3].astype(float)
            a, b = translation_interval(pieces, name, data)
            if name in ("FanL", "FanR"):
                for pivot in corners(a, b):
                    horizontal = np.hypot(pivot[0] - centre[0], pivot[2] - centre[2])
                    distance = np.hypot(horizontal + np.hypot(v[:, 0], v[:, 2]), v[:, 1] + pivot[1] - centre[1])
                    self.assertLessEqual(distance.max(), radius + EPS, name)
            else:
                for shift in corners(a, b):
                    self.assertLessEqual(np.linalg.norm(v + shift - centre, axis=1).max(), radius + EPS, name)
        g, h = data["gantry"], data["heads"]
        # Real vertices at mixed endpoints/intermediates, not just the closed pose.
        for door, gz, hy, hx in itertools.product((0, 0.37, 1),
                (g["minMoveWorld"], (g["minMoveWorld"] + g["maxMoveWorld"]) / 2, g["maxMoveWorld"]),
                (h["minYMoveWorld"], h["maxYMoveWorld"]), (h["minXMoveWorld"], h["maxXMoveWorld"])):
            heads = {"HeadL": np.array((hx, hy, 0)), "HeadR": np.array((h["maxXMoveWorld"] + h["minXMoveWorld"] - hx, h["maxYMoveWorld"] + h["minYMoveWorld"] - hy, 0))}
            for name, points in state_vertices(pieces, data, door, gz, heads, {"FanL": 0.37, "FanR": 1.113}):
                self.assertLessEqual(np.linalg.norm(points - centre, axis=1).max(), radius + EPS, name)
                self.assertLessEqual(points[:, 1].max(), height + EPS, name)

    def test_doors_have_real_pockets_through_the_entire_stroke(self):
        data, pieces = parameters(), source()[2]
        d = data["door"]
        sweep, _ = motion_bounds(pieces, data)
        closed = dict(state_vertices(pieces, data))
        opened = dict(state_vertices(pieces, data, door=1))
        self.assertEqual(d["moveAxis"], "x")
        self.assertAlmostEqual(d["closedMoveWorld"], 0)
        self.assertAlmostEqual(-d["leftOpenMoveWorld"], d["travelWorld"])
        self.assertAlmostEqual(d["rightOpenMoveWorld"], d["travelWorld"])
        for side, label in ((-1, "L"), (1, "R")):
            name = "Door" + label
            with self.subTest(piece=name):
                v, ov = closed[name], opened[name]
                closed_x = d["closedLeftXWorld"] if side < 0 else d["closedRightXWorld"]
                np.testing.assert_allclose(origin(pieces, name), (closed_x, d["pivotYWorld"], d["planeZWorld"]), rtol=0, atol=EPS)
                np.testing.assert_allclose(np.ptp(v, axis=0), (d["leafWidthWorld"], d["leafHeightWorld"], d["leafThicknessWorld"]), rtol=0, atol=EPS)
                self.assertAlmostEqual(v[:, 1].min(), d["bottomYWorld"], delta=EPS)
                self.assertAlmostEqual(v[:, 1].max(), d["topYWorld"], delta=EPS)
                self.assertAlmostEqual(v[:, 0].max() if side < 0 else v[:, 0].min(), 0, delta=EPS)
                self.assertTrue(np.all(side * ov[:, 0] >= d["pocketInnerAbsXWorld"] - EPS))
                self.assertTrue(np.all(side * ov[:, 0] < d["pocketOuterAbsXWorld"] - EPS))
                self.assertGreater(v[:, 2].min(), d["pocketMinZWorld"])
                self.assertLess(v[:, 2].max(), d["pocketMaxZWorld"])
                self.assertLess(v[:, 1].max(), d["pocketTopYWorld"])
                self.assertEqual(fixed_hits(*sweep[name]), [], "Door crosses fixed geometry during continuous travel")
                xa, xb = sorted((side * d["pocketInnerAbsXWorld"], side * d["pocketOuterAbsXWorld"]))
                cavity_low = np.array((xa, data["foundation"]["driveFloorYWorld"] + 2 * EPS, d["pocketMinZWorld"]))
                cavity_high = np.array((xb, d["pocketTopYWorld"], d["pocketMaxZWorld"]))
                self.assertEqual(fixed_hits(cavity_low, cavity_high), [], "Claimed door pocket is filled")
                front = component_named("Base", f"pocket_{label}_front_skin")
                rear = component_named("Base", f"pocket_{label}_rear_skin")
                cap = component_named("Base", f"pocket_{label}_top_cap")
                end = component_named("Base", f"pocket_{label}_end_cap")
                self.assertAlmostEqual(front["low"][2], d["pocketMaxZWorld"], delta=EPS)
                self.assertAlmostEqual(rear["high"][2], d["pocketMinZWorld"], delta=EPS)
                self.assertAlmostEqual(cap["low"][1], d["pocketTopYWorld"], delta=EPS)
                self.assertAlmostEqual(min(side * end["low"][0], side * end["high"][0]), d["pocketOuterAbsXWorld"], delta=EPS)

    def test_full_bridge_head_travel_keeps_product_clearance(self):
        data, pieces = parameters(), source()[2]
        sweep, _ = motion_bounds(pieces, data)
        for name in ("Gantry", "HeadL", "HeadR"):
            self.assertEqual(fixed_hits(*sweep[name]), [], name)
        for side in ("L", "R"):
            tip = sweep["Head" + side][0][1]
            self.assertGreaterEqual(tip + EPS, 48)
            self.assertAlmostEqual(tip, data["heads"]["minimumTipYWorld"], delta=EPS)
            self.assertAlmostEqual(sweep["Nano" + side][0][1], tip, delta=EPS)
        header = component_named("Base", "portal_header")
        self.assertGreaterEqual(header["low"][1] + EPS, 52.5)
        self.assertAlmostEqual(header["low"][1], data["corridor"]["lintelBottomYWorld"], delta=EPS)
        pivot_z = origin(pieces, "Gantry")[2]
        self.assertAlmostEqual(data["gantry"]["minPivotZWorld"], pivot_z + data["gantry"]["minMoveWorld"], delta=EPS)
        self.assertAlmostEqual(data["gantry"]["maxPivotZWorld"], pivot_z + data["gantry"]["maxMoveWorld"], delta=EPS)

    def test_work_lamp_is_one_face_not_a_coincident_second_light(self):
        pieces = source()[2]
        lamp = pieces["WorkLamp"]
        self.assertEqual((len(lamp["vertices"]), len(lamp["indices"])), (4, 2))
        triangles = world_vertices(pieces, "WorkLamp")[lamp["indices"]]
        normal = np.cross(triangles[0, 1] - triangles[0, 0], triangles[0, 2] - triangles[0, 0])
        normal /= np.linalg.norm(normal)
        self.assertTrue(np.all(abs((triangles - triangles[0, 0]) @ normal) < EPS))
        projection = [i for i in range(3) if i != int(np.argmax(abs(normal)))]
        for component in components()["Base"]:
            for triangle in component["triangles"]:
                if np.all(abs((triangle - triangles[0, 0]) @ normal) < EPS):
                    for light in triangles:
                        overlap_area = polygon_area(clip_polygon(light[:, projection], triangle[:, projection]))
                        self.assertLess(overlap_area, EPS, f"WorkLamp overlaps fixed face {component['name']}")

    def test_fans_clear_actual_polygon_holes_for_every_angle(self):
        pieces = source()[2]
        for side in ("L", "R"):
            with self.subTest(fan=side):
                name = "Fan" + side
                centre = origin(pieces, name)
                v = pieces[name]["vertices"][:, :3]
                radial = np.hypot(v[:, 0], v[:, 2]).max()
                ring = component_named("Base", "cooling_ring_" + side)
                triangles = ring["triangles"]
                normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
                normals /= np.linalg.norm(normals, axis=1)[:, None]
                relative = triangles.mean(axis=1) - centre
                inner = (abs(normals[:, 1]) < 1e-6) & (np.sum(normals * relative, axis=1) < -EPS)
                self.assertGreaterEqual(int(inner.sum()), 6, "No inward-facing housing walls")
                inradius = np.abs(np.sum(normals[inner] * (triangles[inner, 0] - centre), axis=1)).min()
                self.assertLess(radial, inradius, "Vertex radius alone misses the polygon hole's smaller inradius")
                well = component_named("Base", "fan_well_" + side)
                self.assertGreater(v[:, 1].min() + centre[1], well["high"][1])
                self.assertLess(v[:, 1].max() + centre[1], ring["high"][1])

    def test_drive_floor_covers_a_continuous_rectangle_at_buildspot_height(self):
        data, pieces = parameters(), source()[2]
        floor = data["foundation"]["driveFloorYWorld"]
        self.assertGreaterEqual(floor, 0)
        self.assertLessEqual(floor, 0.5, "Do not hide grounding problems with a raised driving platform")
        self.assertAlmostEqual(origin(pieces, "BuildSpot")[1], floor, delta=EPS)
        drive = component_named("Base", "foundation_drive_floor")
        self.assertAlmostEqual(drive["high"][1], floor, delta=EPS)
        self.assertAlmostEqual(drive["low"][1], data["foundation"]["skirtBottomYWorld"], delta=EPS)
        corridor = data["corridor"]
        left, right = corridor["minXWorld"], corridor["maxXWorld"]
        rear, front = corridor["rearInnerZWorld"], corridor["apronFrontZWorld"]
        rectangle = np.array(((left, rear), (right, rear), (right, front), (left, front)))
        top = [tri[:, (0, 2)] for tri in drive["triangles"] if np.all(abs(tri[:, 1] - floor) < EPS)]
        clipped = [clip_polygon(tri, rectangle) for tri in top]
        self.assertAlmostEqual(sum(polygon_area(poly) for poly in clipped), (right - left) * (front - rear), delta=1e-3)
        for a, b in itertools.combinations(clipped, 2):
            if polygon_area(a) > EPS and polygon_area(b) > EPS:
                self.assertLess(polygon_area(clip_polygon(a, b)), 1e-4, "Overlaps must not compensate for a floor hole")


class FactoryProductClearanceTests(unittest.TestCase):
    def assert_exit_clear(self, name, idle=False):
        envelope = product_envelope(name, idle)
        hits, margins, bounds = exit_check(envelope, rotating_body=not idle)
        detail = (f"{name} {'idle +Z exit' if idle else 'continuous motion / arbitrary body yaw'}: "
                  f"R={envelope['radius']:.6f}, Ymax={envelope['high'][1]:.6f}, "
                  f"margins={margins}, obstructing geometry={hits}, path={bounds}. "
                  "A negative proxy margin is an unproven pose range, not a native production result.")
        self.assertFalse(hits, detail)
        self.assertGreater(min(margins.values()), 0, detail)

    def test_historical_four_native_inputs_still_match_measured_files(self):
        for name, (_, _, _, digest) in BASELINE.items():
            path = ROOT / "Objects3d" / (NATIVE_NAMES.get(name, name) + ".s3o")
            with self.subTest(product=name):
                self.assertEqual(hashlib.sha256(contents(path)).hexdigest(), digest,
                                 "Product changed: re-measure; do not alter it to pass a new factory test")

    def test_spider_splayed_and_dynamic_envelopes_are_independently_rederived(self):
        idle, moving = product_envelope("spider", True), product_envelope("spider")
        self.assertAlmostEqual(idle["high"][0] - idle["low"][0], 59.2, delta=1e-4)
        self.assertAlmostEqual(moving["high"][0] - moving["low"][0], 69.827464, delta=1e-4)
        self.assertAlmostEqual(moving["radius"], 38.086350, delta=1e-4)
        self.assertAlmostEqual(moving["high"][1], 23.786963, delta=1e-4)

    def test_old_vehicle_free_pitch_and_yaw_match_baseline_not_idle_height(self):
        for name in ("stumpy", "flare", "duron"):
            with self.subTest(product=name):
                result = product_envelope(name)
                radius, minimum, maximum, _ = BASELINE[name]
                self.assertLessEqual(result["radius"], radius + 1e-4)
                self.assertAlmostEqual(result["high"][1], maximum, delta=1e-4)
                self.assertAlmostEqual(product_envelope(name, True)["low"][1], minimum, delta=1e-4)
        self.assertGreater(product_envelope("duron")["high"][1], 45,
                           "Idle Duron height misses the raised gun barrel")

    def test_declared_four_product_proxies_cover_the_rederived_geometry(self):
        proxy = parameters()["productClearanceProxy"]
        self.assertTrue(set(BASELINE).issubset(proxy["products"]))
        for name in BASELINE:
            result, declared = product_envelope(name), proxy["products"][name]
            with self.subTest(product=name):
                self.assertGreaterEqual(declared["horizontalRadiusWorld"] + proxy["roundingPadWorld"], result["radius"])
                self.assertGreaterEqual(declared["maxYWorld"] + proxy["roundingPadWorld"], result["high"][1])
                self.assertEqual(declared["nativeSha256"], BASELINE[name][3])
        self.assertGreaterEqual(proxy["conservativeHorizontalRadiusWorld"], max(product_envelope(n)["radius"] for n in BASELINE))

    def test_original_four_full_motion_straight_corridor(self):
        for name in BASELINE:
            with self.subTest(product=name):
                self.assert_exit_clear(name)

    def test_scout_idle_straight_exit(self):
        self.assert_exit_clear("scout", idle=True)

    def test_scout_full_motion_is_not_assumed_to_fit_r40(self):
        self.assert_exit_clear("scout")

    def test_m1a1_idle_straight_exit_includes_the_long_barrel(self):
        self.assert_exit_clear("m1a1", idle=True)

    def test_m1a1_full_motion_reports_its_own_clearance_gaps(self):
        # Keep the diagnostic red when unrestricted combat does not fit. It is
        # never xfailed or relabelled PASS; --scope production is a distinct,
        # explicit contract. Do not clamp aim, shrink the tank or remove it.
        self.assert_exit_clear("m1a1")

    def test_manifest_marks_all_six_as_products_not_scale_only_references(self):
        references = manifest()["references"]
        for name in CATALOGUE:
            with self.subTest(product=name):
                self.assertIn(name, references, "The current catalogue outgrew the four-product baseline")
                self.assertTrue(references[name]["is_factory_product"], name)


class FactoryMaterialTests(unittest.TestCase):
    def test_final_delivery_is_not_a_gray_or_g1_palette_study(self):
        for origin_name, value in (("data", parameters()["stage"]), ("manifest", manifest()["stage"])):
            self.assertNotRegex(value.lower(), r"\bg1\b|gr[ae]y|palette study", f"{origin_name}: final material acceptance is unfinished")
        diffuse, material = atlas_images()
        for img in (diffuse, material):
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(img.format, "TGA")
        self.assertEqual(diffuse.size, material.size)
        self.assertIn(diffuse.size, ((256, 256), (512, 512)))
        self.assertEqual(diffuse.size[0], parameters()["totals"]["atlasSize"])
        rgb = np.asarray(diffuse)[:, :, :3].astype(int)
        self.assertTrue(np.any(np.ptp(rgb, axis=2) >= 15), "Neutral G1 texture is not the final palette")

    def test_native_atlases_match_final_source_and_channel_semantics(self):
        builder = source()[0]
        expected = builder.make_atlas(gray=False)  # In-memory images only; no saves.
        diffuse, material = atlas_images()
        for actual, wanted in zip((diffuse, material), expected):
            np.testing.assert_array_equal(np.asarray(actual), np.asarray(wanted),
                                          err_msg="Stale/gray atlas does not match the colored source output")
        self.assertEqual(native()[2], TEXTURES)
        self.assertEqual(diffuse.getchannel("A").getextrema(), (0, 255), "Native diffuse A is the team mask")
        self.assertEqual(material.getchannel("R").getextrema(), (0, 0), "Current contract has no baked emission")
        self.assertEqual(material.getchannel("B").getextrema(), (0, 0), "Do not repurpose the unused native channel")
        self.assertGreater(material.getchannel("G").getextrema()[1], 0)
        self.assertEqual(material.getchannel("A").getextrema()[1], 255)
        self.assertEqual(parameters()["workLamp"]["nativeEmission"], 0)

    def test_team_color_is_used_on_visible_upper_geometry_not_only_an_unused_swatch(self):
        diffuse, material = (np.asarray(img) for img in atlas_images())
        height, width = diffuse.shape[:2]
        team_area = 0.0
        for name, piece in native()[1].items():
            if not len(piece["vertices"]):
                continue
            vertices, indices = piece["vertices"], piece["indices"]
            triangles = world_vertices(native()[1], name)[indices]
            uv = vertices[indices, 6:8].mean(axis=1)
            x = np.clip((uv[:, 0] * width).astype(int), 0, width - 1)
            y = np.clip((uv[:, 1] * height).astype(int), 0, height - 1)
            cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            area2 = np.linalg.norm(cross, axis=1)
            upper = (cross[:, 1] > 0.5 * area2) & (triangles[:, :, 1].mean(axis=1) > 40)
            masked = (diffuse[y, x, 3] >= 128) & (material[y, x, 3] >= 128)
            team_area += float(area2[upper & masked].sum() / 2)
            if name in ("DoorL", "DoorR", "Gantry", "HeadL", "HeadR"):
                self.assertTrue(np.all(material[y, x, 3] >= 128), f"Structural {name} became transparent")
        self.assertGreater(team_area, 1, "Roof/upper team markings must occupy real visible triangles")

    def test_glb_embeds_rgb_plus_visibility_not_the_team_alpha(self):
        doc, binary = exchange()
        self.assertEqual(len(doc["materials"]), 1)
        self.assertEqual(len(doc["textures"]), 1)
        self.assertEqual(len(doc["images"]), 1)
        material = doc["materials"][0]
        self.assertEqual(material["alphaMode"], "MASK")
        self.assertAlmostEqual(material["alphaCutoff"], 0.5)
        self.assertFalse(material.get("doubleSided", False))
        pbr = material["pbrMetallicRoughness"]
        self.assertGreaterEqual(pbr["roughnessFactor"], 0.65)
        self.assertLessEqual(pbr["roughnessFactor"], 1)
        self.assertGreaterEqual(pbr["metallicFactor"], 0)
        self.assertLessEqual(pbr["metallicFactor"], 0.3)
        index = pbr["baseColorTexture"]["index"]
        self.assertEqual(index, 0)
        self.assertEqual(doc["textures"][index]["source"], 0)
        image_info = doc["images"][doc["textures"][index]["source"]]
        self.assertNotIn("uri", image_info)
        self.assertEqual(image_info["mimeType"], "image/png")
        self.assertIsInstance(image_info["bufferView"], int)
        self.assertGreaterEqual(image_info["bufferView"], 0)
        self.assertLess(image_info["bufferView"], len(doc["bufferViews"]))
        view = doc["bufferViews"][image_info["bufferView"]]
        start = view.get("byteOffset", 0)
        embedded = Image.open(io.BytesIO(binary[start:start + view["byteLength"]]))
        embedded.load()
        self.assertEqual(embedded.mode, "RGBA")
        first, second = atlas_images()
        self.assertEqual(embedded.size, first.size)
        np.testing.assert_array_equal(np.asarray(embedded)[:, :, :3], np.asarray(first)[:, :, :3])
        np.testing.assert_array_equal(np.asarray(embedded)[:, :, 3], np.asarray(second)[:, :, 3])
        self.assertNotIn("metallicRoughnessTexture", pbr, "Native reflectivity G is not glTF roughness")

    def test_icon_is_a_usable_colored_256_rgba_png(self):
        icon = image(ROOT / "UnitPics/vehicle_factory.png")
        self.assertEqual((icon.size, icon.mode, icon.format), ((256, 256), "RGBA", "PNG"))
        self.assertEqual(icon.getchannel("A").getextrema(), (0, 255))
        pixels = np.asarray(icon)
        opaque = pixels[:, :, 3] >= 128
        self.assertGreater(int(opaque.sum()), 256)
        self.assertTrue(np.any(np.ptp(pixels[:, :, :3].astype(int), axis=2)[opaque] >= 15),
                        "Gray G1/placeholder icon is not final color delivery")


class FactoryIntegrationTests(unittest.TestCase):
    def test_actual_factory_key_and_latest_six_product_order_are_preserved(self):
        name, unit = factory_definition()
        self.assertEqual(name, "factory")
        self.assertEqual(unit["buildoptions"], list(CATALOGUE), "Preserve latest scout/m1a1 additions; never restore the older four-item list")

    def test_active_model_script_and_icon_use_new_existing_targets(self):
        _, unit = factory_definition()
        for field, folder, target in (("objectname", "Objects3d", "vehicle_factory.s3o"),
                ("script", "Scripts", "vehicle_factoryscript.lua"), ("buildpic", "UnitPics", "vehicle_factory.png")):
            with self.subTest(field=field):
                self.assertEqual(unit[field], target, "Existing Factory1 files are not proof the new factory is connected")
                self.assertTrue((ROOT / folder / target).is_file(), str(ROOT / folder / target))
        script = text(ROOT / "Scripts/vehicle_factoryscript.lua")
        values = tokens(script)
        self.assertIn(("identifier", "QueryBuildInfo"), values)
        self.assertIn(("identifier", "QueryNanoPiece"), values)
        self.assertIn(("string", "vehicle_factory_data.lua"), values, "Script must consume the generated contract")
        references = []
        for i, (kind, value) in enumerate(values):
            if kind == "identifier" and value == "piece":
                j = i + 1 + (i + 1 < len(values) and values[i + 1][1] == "(")
                if j < len(values) and values[j][0] == "string":
                    references.append(values[j][1])
        self.assertFalse(set(references) - set(PARENTS), "Script still names old animation pieces")

    def test_input_footprint_and_engine_world_conversion(self):
        _, unit = factory_definition()
        footprint = parameters()["footprint"]
        self.assertEqual((unit["footprintx"], unit["footprintz"]), (12, 10))
        self.assertEqual((footprint["unitDefX"], footprint["unitDefZ"]), (12, 10))
        self.assertEqual(footprint["unitDefCellWorld"], 16)
        self.assertEqual(footprint["gameSquareWorld"], 8)
        self.assertEqual((footprint["engineXSize"], footprint["engineZSize"]), (24, 20))
        self.assertEqual((footprint["worldX"], footprint["worldZ"]), (192, 160))
        self.assertEqual(unit["footprintx"] * footprint["unitDefCellWorld"], footprint["engineXSize"] * footprint["gameSquareWorld"])
        self.assertEqual(unit["footprintz"] * footprint["unitDefCellWorld"], footprint["engineZSize"] * footprint["gameSquareWorld"])
        _, bounds = motion_bounds(source()[2], parameters())
        self.assertTrue(np.all(np.abs(np.asarray(bounds)[:, (0, 2)]) <= np.array((96, 80)) + EPS))

    def test_yardmap_matches_data_rows_content_and_rear_front_orientation(self):
        _, unit = factory_definition()
        candidate = parameters()["yardMapCandidate"]
        # 'Rear two rows' are FIRST in the native text order for facing=0.
        expected = ["oooooooooooo"] * 2 + ["ooooccccoooo"] * 8
        self.assertEqual(candidate["rows"], expected)
        raw = "".join(unit["yardmap"].split())
        self.assertEqual(len(raw), 12 * 10)
        self.assertEqual([raw[i:i + 12] for i in range(0, len(raw), 12)], expected)
        self.assertEqual(Counter(raw), {"o": 88, "c": 32})
        self.assertEqual(candidate["rearBlockedRows"], 2)
        self.assertEqual(candidate["passageCellsWide"], 4)
        self.assertEqual(candidate["passageWorldWidth"], 4 * parameters()["footprint"]["unitDefCellWorld"])
        self.assertEqual(candidate["alwaysBlockedCharacter"], "o")
        self.assertEqual(candidate["openOnlyWhenYardOpenCharacter"], "c")
        self.assertIn("rear -Z", candidate["rowOrder"])
        self.assertIn("front +Z", candidate["rowOrder"])
        self.assertLess(candidate["passageWorldWidth"], parameters()["corridor"]["clearWidthWorld"],
                        "YardMap width and visible opening are different systems, not proof of pathfinding")

    def test_collision_dimensions_match_full_motion_span(self):
        _, unit = factory_definition()
        self.assertEqual(unit["collisionvolumetype"].lower(), "box")
        scale = np.asarray([float(v) for v in unit["collisionvolumescales"].split()])
        offsets = np.asarray([float(v) for v in unit["collisionvolumeoffsets"].split()])
        self.assertEqual(scale.shape, (3,))
        self.assertEqual(offsets.shape, (3,))
        self.assertTrue(np.isfinite(scale).all() and np.isfinite(offsets).all() and np.all(scale > 0))
        _, (low, high) = motion_bounds(source()[2], parameters())
        np.testing.assert_allclose(scale, high - low, rtol=0, atol=0.05,
            err_msg="Chosen collision-size contract is the full moving factory span (currently 192 x 83.5 x 156)")

    def test_collision_centre_matches_native_midpoint_contract(self):
        # Full native smoke verifies the midpoint reference with inside/outside
        # projectile probes. This assertion only checks the delivered numbers.
        _, unit = factory_definition()
        offsets = np.asarray([float(v) for v in unit["collisionvolumeoffsets"].split()])
        scales = np.asarray([float(v) for v in unit["collisionvolumescales"].split()])
        midpoint = np.asarray(native()[0][4:7])
        _, (low, high) = motion_bounds(source()[2], parameters())
        np.testing.assert_allclose(offsets, (0, 0, 0), rtol=0, atol=EPS)
        np.testing.assert_allclose(midpoint + offsets - scales/2, low, rtol=0, atol=EPS)
        np.testing.assert_allclose(midpoint + offsets + scales/2, high, rtol=0, atol=EPS)


class LuaAgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if LUA_PATH is not None:
            sys.path.insert(0, str(LUA_PATH))
        try:
            cls.LuaRuntime = importlib.import_module("lupa.lua51").LuaRuntime
        except ImportError as error:
            if LUA_PATH is not None:
                raise AssertionError(f"--lua-path does not provide the existing lupa.lua51: {LUA_PATH}") from error
            raise unittest.SkipTest("Optional Lua 5.1 agreement check needs existing lupa.lua51/--lua-path; all pure asset checks remain enabled")

    @staticmethod
    def convert(value):
        if not hasattr(value, "items"):
            return value
        mapping = {key: LuaAgreementTests.convert(child) for key, child in value.items()}
        if mapping and set(mapping) == set(range(1, len(mapping) + 1)):
            return [mapping[i] for i in range(1, len(mapping) + 1)]
        return mapping

    @staticmethod
    def omit_nil(value):
        if isinstance(value, dict):
            return {key: LuaAgreementTests.omit_nil(child) for key, child in value.items() if child is not None}
        if isinstance(value, list):
            return [LuaAgreementTests.omit_nil(child) for child in value]
        return value

    def test_generated_data_is_real_lua51_with_matching_nil_locator_semantics(self):
        lua = self.LuaRuntime(unpack_returned_tuples=True)
        actual = self.convert(lua.execute(text(DATA_PATH)))
        self.assertEqual(actual, self.omit_nil(parameters()))

    def test_actual_unitdef_returns_the_same_active_definition_in_lua51(self):
        lua = self.LuaRuntime(unpack_returned_tuples=True)
        lua.execute('function lowerkeys(t) local out={} for k,v in pairs(t) do '
                    'if type(v)=="table" then v=lowerkeys(v) end '
                    'if type(k)=="string" then k=string.lower(k) end out[k]=v end return out end')
        actual = self.convert(lua.execute(text(ROOT / "Units/Factory.lua")))
        name, unit = factory_definition()
        self.assertEqual(actual, {name: self.omit_nil(unit)})


class ZZFrozenInputsTests(unittest.TestCase):
    def test_no_input_changed_during_this_acceptance_run(self):
        # Stat only: do not repeatedly reopen actively produced binary assets.
        for path, expected in INPUT_STAMPS.items():
            with self.subTest(path=str(path)):
                current = path.stat()
                self.assertEqual((current.st_size, current.st_mtime_ns), expected,
                                 "Outputs changed during tests; freeze assets and rerun before drawing conclusions")


def load_tests(loader, tests, pattern):
    if SUITE_SCOPE == "all":
        return tests

    def production_tests(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                yield from production_tests(test)
            elif not test.id().endswith(".test_m1a1_full_motion_reports_its_own_clearance_gaps"):
                yield test

    return unittest.TestSuite(production_tests(tests))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lua-path", type=Path, help="Existing isolated lupa.lua51 directory; installs nothing")
    parser.add_argument("--scope", choices=("all", "production"), default="all",
                        help="all retains unrestricted M1A1 combat clearance; production is a separate, narrower contract")
    options, remaining = parser.parse_known_args()
    LUA_PATH = options.lua_path.resolve() if options.lua_path else None
    SUITE_SCOPE = options.scope
    if SUITE_SCOPE == "production":
        print("Production/exit contract only. Unrestricted M1A1 combat clearance is NOT certified by this selection; run --scope all.", flush=True)
    unittest.main(argv=[sys.argv[0], *remaining])
