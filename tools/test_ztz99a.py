"""Validate the exported S3O/GLB, the animation interface and the texture contract."""

import io
import json
import math
import pathlib
import re
import runpy
import struct
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_s3o(path):
    data = path.read_bytes()
    header = struct.unpack_from("<12si5f4i", data)
    assert header[0] == b"Spring unit\0" and header[1] == 0
    def string(offset):
        assert 0 < offset < len(data)
        return data[offset:data.index(0, offset)].decode("utf-8")
    pieces, visited = {}, set()
    def read(offset, parent, origin):
        assert offset not in visited and offset + 52 <= len(data)
        visited.add(offset)
        record = struct.unpack_from("<10i3f", data, offset)
        name, child_count, child_table, count, vertex_offset, vertex_type, primitive, index_count, index_offset, _ = record[:10]
        assert vertex_type == 0 and primitive == 0
        assert index_count % 3 == 0
        assert vertex_offset + count*32 <= len(data)
        assert index_offset + index_count*4 <= len(data)
        name = string(name)
        assert name not in pieces
        vertices = np.frombuffer(data, dtype="<f4", count=count*8, offset=vertex_offset).reshape(-1, 8)
        indices = np.frombuffer(data, dtype="<i4", count=index_count, offset=index_offset).reshape(-1, 3)
        local = np.asarray(record[-3:])
        position = origin + local
        pieces[name] = {"vertices": vertices, "indices": indices, "parent": parent,
                        "offset": local, "position": position}
        for i in range(child_count):
            child = struct.unpack_from("<i", data, child_table+i*4)[0]
            read(child, name, position)
    read(header[-4], None, np.zeros(3))
    return header, pieces, [string(header[-2]), string(header[-1])]


def load_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A and json_length % 4 == 0
    doc = json.loads(data[20:20+json_length])
    start = 20+json_length
    binary_length, binary_type = struct.unpack_from("<II", data, start)
    assert binary_type == 0x004E4942
    binary = data[start+8:start+8+binary_length]
    assert len(binary) == binary_length
    return doc, binary


def read_accessor(doc, binary, index):
    accessor = doc["accessors"][index]
    view = doc["bufferViews"][accessor["bufferView"]]
    assert "byteStride" not in view and "sparse" not in accessor
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[accessor["type"]]
    dtype = {5126: "<f4", 5125: "<u4"}[accessor["componentType"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    result = np.frombuffer(binary, dtype=dtype, count=accessor["count"]*width, offset=offset)
    return result if width == 1 else result.reshape(-1, width)


def load_track_data(path):
    """Read only the generator's literal Lua table subset, never execute Lua."""
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    table = re.fullmatch(r"\s*return\s*\{\s*(.*?)links\s*=\s*\{\s*(.*?)\},\s*\}\s*", text, re.S)
    assert table, "Track data must return a plain table"
    number = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
    scalar = rf"(\w+)\s*=\s*({number}),\s*"
    assert re.fullmatch(rf"(?:{scalar})+", table[1]), "Non-literal track parameter"
    scalars = re.findall(scalar, table[1])
    data = {key: float(value) for key, value in scalars}
    assert len(data) == len(scalars), "Duplicate track parameter"
    fields = r",\s*".join(rf"{key}\s*=\s*({number})" for key in ("phase", "y", "z", "angle"))
    entry = (rf'\{{\s*{fields},\s*left\s*=\s*"(\w+)",\s*'
             rf'right\s*=\s*"(\w+)"\s*\}},\s*')
    assert re.fullmatch(rf"(?:{entry})+", table[2]), "Links must be an implicit 1-based array of literals"
    data["links"] = [dict(zip(("phase", "y", "z", "angle"), map(float, row[:4])),
                          left=row[4], right=row[5]) for row in re.findall(entry, table[2])]
    return data


def rotation_x(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.asarray(((1, 0, 0), (0, c, -s), (0, s, c)))


def path_pose(data, phase):
    """Independent analytic reference for the unit script's closed track path."""
    s = phase % data["perimeter"]
    h, r, cy = data["halfStraight"], data["radius"], data["centerY"]
    if s <= 2*h:
        return np.asarray((0, cy+r, -h+s)), 0.0
    if s <= 2*h+math.pi*r:
        angle = (s-2*h)/r
        return np.asarray((0, cy+r*math.cos(angle), h+r*math.sin(angle))), angle
    if s <= 4*h+math.pi*r:
        return np.asarray((0, cy-r, 3*h+math.pi*r-s)), math.pi
    angle = math.pi+(s-4*h-math.pi*r)/r
    return np.asarray((0, cy+r*math.cos(angle), -h+r*math.sin(angle))), angle


def original_link(builder):
    mesh = builder.Mesh("reference_link")
    builder.box(mesh, (0, 0, 0), (7.1, 0.5, 1.83), "track")
    builder.box(mesh, (0, 0.31, 0), (4.8, 0.22, 1.25), "rubber")
    builder.box(mesh, (0, 0.36, 0.72), (7.35, 0.28, 0.25), "edge")
    return mesh


def original_idler(builder):
    mesh = builder.Mesh("reference_idler")
    builder.cylinder(mesh, (-2, 0, 0), (2, 0, 0), 4.1, "darkolive", 20)
    for side in (-1, 1):
        x = side*2.1
        builder.annulus(mesh, (x, 0, 0), (side, 0, 0), 3.8, 2.6, "track", 20)
        builder.cylinder(mesh, (x, 0, 0), (x+side*0.15, 0, 0), 1.5, "steel", 12)
        for j in range(10):
            a = j*math.tau/10
            y, z = 3.1*math.sin(a), 3.1*math.cos(a)
            builder.cylinder(mesh, (x, y, z), (x+side*0.12, y, z), 0.35, "black", 6)
    return mesh


def triangle_keys(piece):
    points = piece["vertices"][:, :3].astype(float) + piece["position"]
    return {tuple(sorted(map(tuple, triangle)))
            for triangle in np.round(points[piece["indices"]], 4)}


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header, cls.pieces, cls.textures = load_s3o(ROOT/"Objects3d"/"ztz99a.s3o")
        cls.gltf, cls.binary = load_glb(ROOT/"Objects3d"/"ztz99a.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}
        cls.manifest = json.loads((ROOT/"tools"/"previews"/"ztz99a_manifest.json").read_text(encoding="utf-8"))
        cls.track = load_track_data(ROOT/"Scripts"/"ztz99a_track_data.lua")
        cls.builder = SimpleNamespace(**runpy.run_path(str(ROOT/"tools"/"build_ztz99a.py")))
        cls.generated = {piece.name: piece for piece, _ in cls.builder.walk(cls.builder.make_model())}
        cls.reference_link = original_link(cls.builder)
        cls.reference_idler = original_idler(cls.builder)

    def test_unit_uses_exported_native_model_and_icon(self):
        definition = (ROOT/"Units"/"mbt.lua").read_text(encoding="utf-8")
        model = re.search(r'ObjectName\s*=\s*"([^"]+)"', definition).group(1)
        icon = re.search(r'BuildPic\s*=\s*"([^"]+)"', definition).group(1)
        self.assertEqual(model, "ztz99a.s3o")
        self.assertTrue((ROOT/"UnitPics"/icon).is_file())

    def test_all_animation_pieces_exist_and_pivots_are_nested(self):
        source = (ROOT/"Scripts"/"mbtscript.lua").read_text(encoding="utf-8")
        # Static references are a subset: the script resolves track names dynamically.
        references = set(re.findall(r'''\bpiece\s*(?:\(\s*)?["']([^"']+)["']''', source))
        self.assertFalse(references - set(self.pieces), "Missing a statically referenced animation piece")
        self.assertEqual(self.pieces["Turret"]["parent"], "Base")
        self.assertEqual(self.pieces["Gun"]["parent"], "Turret")
        self.assertEqual(self.pieces["Flare"]["parent"], "Gun")
        self.assertGreater(self.pieces["Flare"]["position"][2], 75)
        self.assertEqual(self.pieces["Flare"]["offset"][0], 0)
        self.assertEqual(self.pieces["Flare"]["offset"][1], 0)
        for side, label in ((-1, "L"), (1, "R")):
            for i, z in enumerate((24.5, 14.7, 4.9, -4.9, -14.7, -24.5), 1):
                wheel = self.pieces[f"Wheel{label}{i}"]
                self.assertEqual(wheel["parent"], "Base")
                np.testing.assert_allclose(wheel["offset"], (side*17.8, 6.15, z), rtol=0, atol=2e-6)

    def test_native_indices_normals_and_uvs(self):
        for name, piece in self.pieces.items():
            with self.subTest(piece=name):
                v, triangles = piece["vertices"], piece["indices"]
                if not len(v):
                    continue
                self.assertTrue(np.isfinite(v).all())
                self.assertGreaterEqual(triangles.min(), 0)
                self.assertLess(triangles.max(), len(v))
                self.assertTrue(np.allclose(np.linalg.norm(v[:,3:6], axis=1), 1, atol=1e-5))
                self.assertTrue(((v[:,6:] >= 0) & (v[:,6:] <= 1)).all())
                a,b,c = v[triangles[:,0],:3], v[triangles[:,1],:3], v[triangles[:,2],:3]
                cross = np.cross(b-a,c-a)
                self.assertTrue((np.linalg.norm(cross, axis=1) > 1e-7).all(), "Degenerate triangle")
                normals = v[triangles,3:6].mean(axis=1)
                self.assertTrue((np.sum(cross*normals, axis=1) > 0).all(), "Reversed triangle")

    def test_ground_and_bounds(self):
        points = np.concatenate([p["vertices"][:,:3]+p["position"] for p in self.pieces.values() if len(p["vertices"])])
        self.assertGreaterEqual(points[:,1].min(), -1e-5)
        self.assertLessEqual(points[:,1].max(), self.header[3]+1e-4)
        distances = np.linalg.norm(points-np.asarray(self.header[4:7]), axis=1)
        self.assertLessEqual(distances.max(), self.header[2]+1e-4)
        self.assertLess(points[:,0].max()-points[:,0].min(), 48)
        np.testing.assert_allclose(points.min(axis=0), self.manifest["bounds"]["min"], rtol=0, atol=4e-6)
        np.testing.assert_allclose(points.max(axis=0), self.manifest["bounds"]["max"], rtol=0, atol=4e-6)

    def test_texture_visibility_and_team_mask(self):
        self.assertEqual(self.textures, ["ztz99a_diffuse.tga", "ztz99a_material.tga"])
        first = Image.open(ROOT/"UnitTextures"/self.textures[0]).convert("RGBA")
        second = Image.open(ROOT/"UnitTextures"/self.textures[1]).convert("RGBA")
        self.assertEqual(first.size, (1024,1024))
        self.assertEqual(second.size, first.size)
        self.assertEqual(first.getchannel("A").getextrema(), (0,255))
        self.assertEqual(second.getchannel("A").getextrema(), (0,255))
        self.assertEqual(first.getpixel((100,100))[3], 0, "Camouflage must not be replaced by team color")
        self.assertEqual(second.getpixel((100,100))[3], 255, "Armor must be opaque")
        self.assertEqual(second.getpixel((10,522))[3], 0, "Decal background must be cut out")

    def test_glb_matches_hierarchy_and_has_embedded_masked_texture(self):
        self.assertEqual(len(self.nodes), len(self.gltf["nodes"]))
        self.assertEqual(set(self.nodes), set(self.pieces))
        parents = {}
        for node in self.gltf["nodes"]:
            np.testing.assert_allclose(node["translation"], self.pieces[node["name"]]["offset"], rtol=0, atol=2e-6)
            for child in node.get("children", []):
                self.assertNotIn(child, parents)
                parents[child] = node["name"]
        for i, node in enumerate(self.gltf["nodes"]):
            self.assertEqual(parents.get(i), self.pieces[node["name"]]["parent"])
        roots = self.gltf["scenes"][self.gltf["scene"]]["nodes"]
        self.assertEqual([self.gltf["nodes"][i]["name"] for i in roots], ["Base"])
        for view in self.gltf["bufferViews"]:
            self.assertEqual(view.get("byteOffset",0) % 4, 0)
            self.assertLessEqual(view.get("byteOffset",0)+view["byteLength"], len(self.binary))
        image = self.gltf["images"][0]
        self.assertNotIn("uri", image)
        view = self.gltf["bufferViews"][image["bufferView"]]
        png = self.binary[view["byteOffset"]:view["byteOffset"]+view["byteLength"]]
        texture = Image.open(io.BytesIO(png))
        self.assertEqual(texture.mode, "RGBA")
        self.assertEqual(texture.getchannel("A").getextrema(), (0,255))
        self.assertEqual(self.gltf["materials"][0]["alphaMode"], "MASK")

    def test_native_uv_origin_matches_the_engine_texture_loader(self):
        for node in self.gltf["nodes"]:
            if "mesh" not in node:
                continue
            primitive = self.gltf["meshes"][node["mesh"]]["primitives"][0]
            uv = read_accessor(self.gltf, self.binary, primitive["attributes"]["TEXCOORD_0"])
            np.testing.assert_allclose(self.pieces[node["name"]]["vertices"][:,6:], uv, rtol=0, atol=6e-8,
                                       err_msg="Native S3O needs top-origin UVs, not the preview renderer's bottom-origin UVs")

    def test_previous_asset_was_preserved(self):
        self.assertTrue((ROOT/"Objects3d"/"MBT.glb").is_file())
        self.assertTrue((ROOT/"UnitTextures"/"MBTtexture.tga").is_file())

    def test_generated_track_contract_matches_manifest_and_source(self):
        self.assertEqual(self.manifest["track_data"], "Scripts/ztz99a_track_data.lua")
        self.assertEqual(self.track, self.manifest["track"])
        self.assertEqual(self.track, self.builder.make_track_data(), "Regenerate assets after changing the path")
        expected = {"linkCount": 84, "halfStraight": 31, "radius": 7, "centerY": 7.6,
                    "halfWidth": 17.8, "perimeter": 124+14*math.pi, "wheelRadius": 5.12,
                    "idlerRadius": 4.1, "pieceCount": 188}
        self.assertEqual(set(self.track), set(expected) | {"links"})
        for key, value in expected.items():
            self.assertEqual(self.track[key], value)
        links = self.track["links"]
        self.assertEqual(len(links), self.track["linkCount"])
        pitch = self.track["perimeter"]/self.track["linkCount"]
        for i, link in enumerate(links, 1):
            self.assertEqual(set(link), {"phase", "y", "z", "angle", "left", "right"})
            self.assertEqual((link["left"], link["right"]), (f"TrackL{i:02d}", f"TrackR{i:02d}"))
            self.assertAlmostEqual(link["phase"], (i-0.5)*pitch, places=12)
            self.assertGreaterEqual(link["angle"], 0)
            self.assertLess(link["angle"], math.tau)
        phases = [link["phase"] for link in links]
        np.testing.assert_allclose(np.diff(phases+[phases[0]+self.track["perimeter"]]), pitch, rtol=0, atol=1e-12)

    def test_complete_piece_set_and_track_parentage(self):
        original = {"Base", "Turret", "Gun", "Flare"} | {f"Wheel{side}{i}" for side in "LR" for i in range(1, 7)}
        links = {link[key] for link in self.track["links"] for key in ("left", "right")}
        idlers = {f"Idler{side}{end}" for side in "LR" for end in ("Front", "Rear")}
        expected = original | links | idlers
        self.assertEqual(len(links), 168)
        self.assertEqual(len(self.pieces), 188)
        self.assertEqual(set(self.pieces), expected)
        self.assertEqual(set(self.generated), expected)
        self.assertEqual(set(self.manifest["pieces"]), expected)
        self.assertEqual(len(self.manifest["pieces"]), self.track["pieceCount"])
        for name in links | idlers:
            self.assertEqual(self.pieces[name]["parent"], "Base", name)
            self.assertNotIn("rotation", self.nodes[name], "Rest rotations belong in vertices, not only in GLB nodes")
            self.assertNotIn("matrix", self.nodes[name])
            self.assertNotIn("scale", self.nodes[name])

    def test_track_rest_offsets_and_baked_rotation_preserve_shoe_geometry(self):
        reference = self.reference_link
        expected_uv = np.asarray(reference.uvs).copy()
        expected_uv[:, 1] = 1-expected_uv[:, 1]
        for link in self.track["links"]:
            point, angle = path_pose(self.track, link["phase"])
            np.testing.assert_allclose((link["y"], link["z"], link["angle"]), (*point[1:], angle), rtol=0, atol=1e-12)
            for side, key in ((-1, "left"), (1, "right")):
                name = link[key]
                with self.subTest(piece=name):
                    piece = self.pieces[name]
                    center = point + (side*self.track["halfWidth"], 0, 0)
                    np.testing.assert_allclose(piece["offset"], center, rtol=0, atol=2e-6)
                    # Undo the baked angle to recover the original three boxes.
                    unrotate = rotation_x(-link["angle"]).T
                    np.testing.assert_allclose(piece["vertices"][:, :3] @ unrotate, reference.positions, rtol=0, atol=3e-7)
                    np.testing.assert_allclose(piece["vertices"][:, 3:6] @ unrotate, reference.normals, rtol=0, atol=1e-7)
                    np.testing.assert_array_equal(piece["vertices"][:, 6:], expected_uv)
                    np.testing.assert_array_equal(piece["indices"], np.asarray(reference.indices).reshape(-1, 3))

    def test_idler_pivots_and_original_geometry(self):
        reference = self.reference_idler
        expected = np.column_stack((reference.positions, reference.normals, reference.uvs)).astype("<f4")
        expected[:, 7] = 1-expected[:, 7]
        for side, label in ((-1, "L"), (1, "R")):
            for end, z in (("Front", 33.3), ("Rear", -33.3)):
                piece = self.pieces[f"Idler{label}{end}"]
                np.testing.assert_allclose(piece["offset"], (side*17.8, 8.9, z), rtol=0, atol=2e-6)
                np.testing.assert_array_equal(piece["vertices"], expected)
                np.testing.assert_array_equal(piece["indices"], np.asarray(reference.indices).reshape(-1, 3))

    def test_split_geometry_has_no_duplicates_or_hidden_frames(self):
        counts = {name: len(piece["indices"]) for name, piece in self.pieces.items()}
        expected = {"Base": 4716, "Turret": 4912, "Gun": 1692, "Flare": 0}
        expected.update({f"Wheel{side}{i}": 1352 for side in "LR" for i in range(1, 7)})
        expected.update({link[key]: 36 for link in self.track["links"] for key in ("left", "right")})
        expected.update({f"Idler{side}{end}": 644 for side in "LR" for end in ("Front", "Rear")})
        self.assertEqual(counts, expected)
        self.assertEqual(sum(counts.values()), 36168)
        self.assertEqual(self.manifest["triangles"], sum(counts.values()))
        moving = set()
        for name, piece in self.pieces.items():
            if name.startswith(("Track", "Idler")):
                triangles = triangle_keys(piece)
                self.assertTrue(moving.isdisjoint(triangles), name)
                self.assertEqual(len(triangles), counts[name], name)
                moving.update(triangles)
        self.assertTrue(triangle_keys(self.pieces["Base"]).isdisjoint(moving), "Moving geometry is still baked into Base")

    def test_exports_match_generated_positions_normals_and_indices(self):
        for name, piece in self.pieces.items():
            with self.subTest(piece=name):
                source, node = self.generated[name], self.nodes[name]
                if source.mesh is None:
                    self.assertEqual(len(piece["vertices"]), 0)
                    self.assertNotIn("mesh", node)
                    continue
                primitives = self.gltf["meshes"][node["mesh"]]["primitives"]
                self.assertEqual(len(primitives), 1)
                primitive = primitives[0]
                self.assertEqual((primitive["mode"], primitive["material"]), (4, 0))
                for attribute, field, section in (("POSITION", "positions", slice(0, 3)), ("NORMAL", "normals", slice(3, 6))):
                    exported = read_accessor(self.gltf, self.binary, primitive["attributes"][attribute])
                    np.testing.assert_array_equal(exported, piece["vertices"][:, section])
                    np.testing.assert_array_equal(exported, np.asarray(getattr(source.mesh, field), dtype="<f4"))
                indices = read_accessor(self.gltf, self.binary, primitive["indices"]).reshape(-1, 3)
                np.testing.assert_array_equal(indices, piece["indices"])
                np.testing.assert_array_equal(indices.ravel(), source.mesh.indices)

    def test_glb_mesh_reuse_never_aliases_different_rest_angles(self):
        angles = {}
        for link in self.track["links"]:
            left, right = (self.nodes[link[key]]["mesh"] for key in ("left", "right"))
            self.assertEqual(left, right)
            if link["angle"] in angles:
                self.assertEqual(left, angles[link["angle"]])
            else:
                self.assertNotIn(left, angles.values())
                angles[link["angle"]] = left
        for prefix in ("Wheel", "Idler"):
            self.assertEqual(len({node["mesh"] for name, node in self.nodes.items() if name.startswith(prefix)}), 1)
        self.assertEqual(len(self.gltf["meshes"]), len(angles)+5)

    def test_closed_path_has_unit_speed_and_continuous_frame(self):
        d = self.track
        perimeter, straight, arc = d["perimeter"], 2*d["halfStraight"], math.pi*d["radius"]
        joints = (0, straight, straight+arc, 2*straight+arc, perimeter)
        samples = [*joints, *(link["phase"] for link in d["links"])]
        for phase in samples:
            point, angle = self.builder.track_pose(phase)
            reference, reference_angle = path_pose(d, phase)
            np.testing.assert_allclose(point, reference, rtol=0, atol=1e-12)
            np.testing.assert_allclose(rotation_x(angle), rotation_x(reference_angle), rtol=0, atol=1e-12)
            for cycles in (-3, -1, 1, 3):
                repeated, repeated_angle = self.builder.track_pose(phase+cycles*perimeter)
                np.testing.assert_allclose(repeated, point, rtol=0, atol=1e-12)
                np.testing.assert_allclose(rotation_x(repeated_angle), rotation_x(angle), rtol=0, atol=1e-12)
            _, tangent = self.builder.track_point(phase)
            eps = 1e-5
            before = self.builder.track_pose(phase-eps)[0]
            after = self.builder.track_pose(phase+eps)[0]
            np.testing.assert_allclose((after-before)/(2*eps), tangent, rtol=0, atol=2e-6)
            self.assertAlmostEqual(np.linalg.norm(tangent), 1, places=12)
            np.testing.assert_allclose(tangent, rotation_x(angle) @ (0, 0, 1), rtol=0, atol=1e-12)
        for phase in joints:
            before, a = self.builder.track_pose(phase-1e-7)
            after, b = self.builder.track_pose(phase+1e-7)
            np.testing.assert_allclose(before, after, rtol=0, atol=3e-7)
            np.testing.assert_allclose(rotation_x(a), rotation_x(b), rtol=0, atol=3e-8)

    def test_motion_poses_keep_links_on_path_and_within_model_bounds(self):
        d, perimeter = self.track, self.track["perimeter"]
        links = {link[key]: (link, side) for link in d["links"] for key, side in (("left", -1), ("right", 1))}
        poses = [(phase, phase) for phase in np.linspace(-perimeter, perimeter, 17)]
        poses += [(0.37*perimeter, -0.37*perimeter), (perimeter/168, 0),
                  (-d["links"][0]["phase"], 0), (3.125*perimeter, -3.125*perimeter)]
        for left_phase, right_phase in poses:
            with self.subTest(left=left_phase, right=right_phase):
                points = []
                for name, piece in self.pieces.items():
                    if not len(piece["vertices"]):
                        continue
                    local, offset = piece["vertices"][:, :3].astype(float), piece["position"].copy()
                    if name in links:
                        link, side = links[name]
                        phase = left_phase if side < 0 else right_phase
                        center, angle = path_pose(d, link["phase"]+phase)
                        delta = rotation_x(angle-link["angle"]).T
                        local = local @ delta
                        offset += center - (0, link["y"], link["z"])
                        expected = np.asarray(self.reference_link.positions) @ rotation_x(angle).T
                        expected += center + (side*d["halfWidth"], 0, 0)
                        np.testing.assert_allclose(local+offset, expected, rtol=0, atol=3e-6)
                        normals = piece["vertices"][:, 3:6] @ delta
                        np.testing.assert_allclose(normals, np.asarray(self.reference_link.normals) @ rotation_x(angle).T,
                                                   rtol=0, atol=1e-7)
                    elif name.startswith(("Wheel", "Idler")):
                        phase = left_phase if name.startswith(("WheelL", "IdlerL")) else right_phase
                        radius = d["wheelRadius"] if name.startswith("Wheel") else d["idlerRadius"]
                        local = local @ rotation_x(phase/radius).T
                    points.append(local+offset)
                points = np.concatenate(points)
                self.assertTrue(np.isfinite(points).all())
                low, high = np.asarray(self.manifest["bounds"]["min"]), np.asarray(self.manifest["bounds"]["max"])
                low[1] = 0  # Curved shoes can dip slightly below the rest-pose minimum, never below ground.
                self.assertTrue((points.min(axis=0) >= low-1e-5).all())
                self.assertTrue((points.max(axis=0) <= high+1e-5).all())
                distance = np.linalg.norm(points-np.asarray(self.header[4:7]), axis=1)
                self.assertLessEqual(distance.max(), self.header[2]+1e-4)


if __name__ == "__main__":
    unittest.main()
