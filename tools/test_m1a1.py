"""Validate the low-poly Abrams asset, animation rig, and native/exchange exports."""

import io
import json
import math
import pathlib
import re
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_m1a1 as builder
from test_ztz99a import load_glb, load_s3o, load_track_data, path_pose, read_accessor, rotation_x

ROOT = pathlib.Path(__file__).resolve().parents[1]


class M1A1ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header, cls.pieces, cls.textures = load_s3o(ROOT/"Objects3d"/"m1a1.s3o")
        cls.gltf, cls.binary = load_glb(ROOT/"Objects3d"/"m1a1.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}
        cls.manifest = json.loads((ROOT/"tools"/"previews"/"m1a1_manifest.json").read_text(encoding="utf-8"))
        cls.track = load_track_data(ROOT/"Scripts"/"m1a1_track_data.lua")
        cls.generated = {p.name: p for p, _ in builder.walk(builder.make_model())}

    def test_distinct_unit_model_weapon_and_test_entry(self):
        source = (ROOT/"Units"/"m1a1.lua").read_text(encoding="utf-8")
        for field, value in (("ObjectName", "m1a1.s3o"), ("script", "m1a1script.lua"),
                             ("BuildPic", "m1a1.png"), ("Side", "Abrams")):
            self.assertRegex(source, rf'{field}\s*=\s*"{re.escape(value)}"')
        self.assertIn('name = "M1A1Gun"', source)
        weapon = (ROOT/"Weapons"/"M1A1Gun.lua").read_text(encoding="utf-8")
        self.assertIn('"120mm Cannon"', weapon)
        launcher = (ROOT/"Test-M1.bat").read_text(encoding="utf-8")
        self.assertIn("--only-local", launcher)
        self.assertIn(".mygame-m1-test", launcher)
        start = (ROOT/"tools"/"m1a1_test.txt").read_text(encoding="utf-8")
        self.assertIn("Side=Abrams;", start)
        self.assertIn("Side=Beefys;", start)
        self.assertIn("ShortName=NullAI;", start)
        self.assertIn("TeamDeathMode=none;", start)

    def test_death_effect_is_defined_without_damage_or_terrain_changes(self):
        unit = (ROOT/"Units"/"m1a1.lua").read_text(encoding="utf-8")
        for field in ("ExplodeAs", "SelfDestructAs"):
            self.assertRegex(unit, rf'{field}\s*=\s*"M1A1Death"')
        effect = (ROOT/"Weapons"/"M1A1Death.lua").read_text(encoding="utf-8")
        self.assertIn('local weaponName = "M1A1Death"', effect)
        self.assertRegex(effect, r"damage\s*=\s*\{\s*default\s*=\s*0\s*\}")
        for field in ("areaOfEffect", "impulseFactor", "craterMult", "craterBoost"):
            self.assertRegex(effect, rf'{field}\s*=\s*0\s*,')

    def test_low_poly_budget_counts_instances_not_only_unique_meshes(self):
        count = sum(len(p["indices"]) for p in self.pieces.values())
        self.assertEqual(count, self.manifest["triangles"])
        self.assertLessEqual(count, 3200)
        self.assertGreater(count, 1000)
        old = json.loads((ROOT/"tools"/"previews"/"ztz99a_manifest.json").read_text(encoding="utf-8"))
        self.assertLess(count, old["triangles"]/8)
        glb_count = sum(len(read_accessor(self.gltf, self.binary,
                        self.gltf["meshes"][n["mesh"]]["primitives"][0]["indices"]))//3
                        for n in self.nodes.values() if "mesh" in n)
        self.assertEqual(glb_count, count)

    def test_finite_indexed_geometry_and_hard_face_normals(self):
        for name, piece in self.pieces.items():
            with self.subTest(piece=name):
                v, triangles = piece["vertices"], piece["indices"]
                if not len(v):
                    continue
                self.assertTrue(np.isfinite(v).all())
                self.assertGreaterEqual(triangles.min(), 0)
                self.assertLess(triangles.max(), len(v))
                np.testing.assert_allclose(np.linalg.norm(v[:, 3:6], axis=1), 1, atol=1e-6)
                self.assertTrue(((v[:, 6:] >= 0) & (v[:, 6:] <= 1)).all())
                a, b, c = (v[triangles[:, i], :3] for i in range(3))
                cross = np.cross(b-a, c-a)
                self.assertTrue((np.linalg.norm(cross, axis=1) > 1e-7).all())
                normals = v[triangles, 3:6]
                self.assertTrue((np.sum(cross*normals[:, 0], axis=1) > 0).all())
                np.testing.assert_allclose(normals[:, 0], normals[:, 1], atol=1e-6)
                np.testing.assert_allclose(normals[:, 0], normals[:, 2], atol=1e-6)

    def test_exact_seven_wheel_rig_and_nested_weapon_pivots(self):
        expected = {"Base", "Turret", "Gun", "Flare"}
        for side, label in ((-1, "L"), (1, "R")):
            for i, z in enumerate((26.4, 17.6, 8.8, 0, -8.8, -17.6, -26.4), 1):
                name = f"Wheel{label}{i}"
                expected.add(name)
                self.assertEqual(self.pieces[name]["parent"], "Base")
                np.testing.assert_allclose(self.pieces[name]["position"],
                                           (side*17.4, 5.25, z), atol=2e-6)
            for end in ("Front", "Rear"):
                expected.add(f"Idler{label}{end}")
            expected.update(f"Track{label}{i:02d}" for i in range(1, 41))
        self.assertEqual(set(self.pieces), expected)
        self.assertEqual(len(self.pieces), 102)
        self.assertEqual(self.pieces["Turret"]["parent"], "Base")
        self.assertEqual(self.pieces["Gun"]["parent"], "Turret")
        self.assertEqual(self.pieces["Flare"]["parent"], "Gun")
        self.assertGreater(self.pieces["Flare"]["position"][2], 70)
        self.assertEqual(self.pieces["Flare"]["offset"][0], 0)
        self.assertEqual(self.pieces["Flare"]["offset"][1], 0)

    def test_bounds_ground_and_low_profile(self):
        points = np.concatenate([p["vertices"][:, :3]+p["position"]
                                 for p in self.pieces.values() if len(p["vertices"])])
        low, high = points.min(axis=0), points.max(axis=0)
        self.assertGreaterEqual(low[1], 0)
        self.assertLess(high[1], 40)
        self.assertLess(high[0]-low[0], 45)
        self.assertGreater(high[2]-low[2], 110)
        self.assertLess(self.pieces["Gun"]["position"][1], 24)
        self.assertLess(np.linalg.norm(points-np.asarray(self.header[4:7]), axis=1).max(), self.header[2]+1e-4)
        np.testing.assert_allclose(low, self.manifest["bounds"]["min"], atol=4e-6)
        np.testing.assert_allclose(high, self.manifest["bounds"]["max"], atol=4e-6)

    def test_native_and_glb_match_source_and_each_other(self):
        self.assertEqual(set(self.nodes), set(self.pieces))
        self.assertEqual(set(self.generated), set(self.pieces))
        self.assertEqual(set(self.manifest["pieces"]), set(self.pieces))
        parents = {child: node["name"] for node in self.gltf["nodes"] for child in node.get("children", [])}
        for i, node in enumerate(self.gltf["nodes"]):
            name = node["name"]
            piece, mesh = self.pieces[name], self.generated[name].mesh
            self.assertEqual(parents.get(i), piece["parent"])
            np.testing.assert_allclose(node["translation"], piece["offset"], atol=2e-6)
            if mesh is None:
                self.assertNotIn("mesh", node)
                continue
            v = piece["vertices"]
            primitive = self.gltf["meshes"][node["mesh"]]["primitives"][0]
            for field, columns in (("POSITION", slice(0, 3)), ("NORMAL", slice(3, 6)), ("TEXCOORD_0", slice(6, 8))):
                actual = read_accessor(self.gltf, self.binary, primitive["attributes"][field])
                np.testing.assert_array_equal(actual, v[:, columns])
            np.testing.assert_array_equal(read_accessor(self.gltf, self.binary, primitive["indices"]),
                                          piece["indices"].ravel())
            np.testing.assert_allclose(v[:, :3], mesh.positions, atol=2e-6)
            np.testing.assert_allclose(v[:, 3:6], mesh.normals, atol=1e-6)
            expected_uv = np.asarray(mesh.uvs).copy()
            expected_uv[:, 1] = 1-expected_uv[:, 1]
            np.testing.assert_allclose(v[:, 6:8], expected_uv, atol=1e-7)

    def test_small_flat_palette_and_s3o_alpha_contract(self):
        self.assertEqual(self.textures, ["m1a1_diffuse.tga", "m1a1_material.tga"])
        diffuse = Image.open(ROOT/"UnitTextures"/self.textures[0]).convert("RGBA")
        material = Image.open(ROOT/"UnitTextures"/self.textures[1]).convert("RGBA")
        self.assertEqual(diffuse.size, (256, 256))
        self.assertEqual(material.size, diffuse.size)
        for name, rgb in builder.COLORS.items():
            x0, y0, x1, y1 = builder.RECTS[name]
            colors = diffuse.crop((x0, y0, x1, y1)).getcolors()
            self.assertEqual(len(colors), 1, "No noisy photographic/camouflage swatches")
            expected = rgb+(255 if name == "team" else 0,)
            self.assertEqual(colors[0][1], expected)
            self.assertEqual(material.getpixel((x0, y0))[3], 255)
        self.assertEqual(material.getpixel((133, 5))[3], 0)
        self.assertEqual(material.getpixel((192, 24))[3], 255)
        self.assertEqual(material.getchannel("R").getextrema(), (0, 0))

    def test_glb_embeds_the_correct_visibility_texture(self):
        image = self.gltf["images"][0]
        self.assertNotIn("uri", image)
        view = self.gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        png = Image.open(io.BytesIO(self.binary[start:start+view["byteLength"]])).convert("RGBA")
        first = Image.open(ROOT/"UnitTextures"/self.textures[0]).convert("RGBA")
        second = Image.open(ROOT/"UnitTextures"/self.textures[1]).convert("RGBA")
        np.testing.assert_array_equal(np.asarray(png)[:, :, :3], np.asarray(first)[:, :, :3])
        np.testing.assert_array_equal(np.asarray(png)[:, :, 3], np.asarray(second)[:, :, 3])
        self.assertEqual(self.gltf["materials"][0]["alphaMode"], "MASK")
        self.assertIn("M1A1", self.gltf["asset"]["generator"])
        for view in self.gltf["bufferViews"]:
            self.assertEqual(view.get("byteOffset", 0) % 4, 0)
            self.assertLessEqual(view.get("byteOffset", 0)+view["byteLength"], len(self.binary))

    def test_generated_track_parameters_and_baked_shoe_poses(self):
        self.assertEqual(self.track, self.manifest["track"])
        self.assertEqual(self.track, builder.make_track_data())
        self.assertEqual(self.track["wheelCount"], 7)
        self.assertEqual(self.track["linkCount"], 40)
        self.assertEqual(self.track["pieceCount"], len(self.pieces))
        canonical = None
        for rest in self.track["links"]:
            center, angle = path_pose(self.track, rest["phase"])
            self.assertAlmostEqual(angle, rest["angle"], places=10)
            for side, key in ((-1, "left"), (1, "right")):
                piece = self.pieces[rest[key]]
                self.assertEqual(piece["parent"], "Base")
                expected = center+np.asarray((side*self.track["halfWidth"], 0, 0))
                np.testing.assert_allclose(piece["position"], expected, atol=2e-6)
                vertices = piece["vertices"][:, :3] @ rotation_x(angle)
                if canonical is None:
                    canonical = vertices
                np.testing.assert_allclose(vertices, canonical, atol=1e-6)
                # All animated phases stay above the ground, including arc corners.
                for phase in np.linspace(0, self.track["perimeter"], 81):
                    position, pose_angle = path_pose(self.track, phase)
                    posed = vertices @ rotation_x(pose_angle).T+position
                    self.assertGreaterEqual(posed[:, 1].min(), -1e-6)

    def test_existing_tank_and_starting_side_are_preserved(self):
        for name in ("MBT.glb", "ztz99a.glb", "ztz99a.s3o"):
            self.assertTrue((ROOT/"Objects3d"/name).is_file())
        side = (ROOT/"GameData"/"SideData.lua").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'startUnit\s*=\s*"([^"]+)"', side), ["mbt", "m1a1"])
        self.assertIn('ObjectName     = "ztz99a.s3o"', (ROOT/"Units"/"mbt.lua").read_text(encoding="utf-8"))
        old_start = (ROOT/"tools"/"mbt_test.txt").read_text(encoding="utf-8")
        self.assertEqual(old_start.count("Side=Beefys;"), 2)

    def test_icon_is_ready_to_use_without_python(self):
        image = Image.open(ROOT/"UnitPics"/"m1a1.png")
        self.assertEqual(image.size, (256, 256))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
        for name in ("m1a1_front.png", "m1a1_rear.png", "m1a1_views.png"):
            self.assertTrue((ROOT/"tools"/"previews"/name).is_file())


if __name__ == "__main__":
    unittest.main()
