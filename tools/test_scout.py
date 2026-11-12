"""Validate the low-poly FV-6 Scout asset, rig contract and native/exchange exports."""

import io
import json
import pathlib
import re
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_scout as builder
from test_ztz99a import load_glb, load_s3o, read_accessor

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ScoutModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header, cls.pieces, cls.textures = load_s3o(ROOT/"Objects3d"/"scout.s3o")
        cls.gltf, cls.binary = load_glb(ROOT/"Objects3d"/"scout.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}
        cls.manifest = json.loads((ROOT/"tools"/"previews"/"scout_manifest.json").read_text(encoding="utf-8"))
        cls.generated = {p.name: p for p, _ in builder.walk(builder.make_model())}

    def test_unit_weapon_and_rig_are_wired(self):
        unit = (ROOT/"Units"/"scout.lua").read_text(encoding="utf-8")
        for field, value in (("ObjectName", "scout.s3o"), ("script", "scoutscript.lua"),
                             ("BuildPic", "scout.png"), ("Side", "Abrams")):
            self.assertRegex(unit, rf'{field}\s*=\s*"{re.escape(value)}"')
        self.assertIn('name = "ScoutGun"', unit)
        self.assertRegex(unit, r"collisionVolumeScales\s*=\s*\"33 20 52\"")
        self.assertRegex(unit, r"TurnInPlace\s*=\s*false")
        self.assertRegex(unit, r"TurnInPlaceSpeedLimit\s*=\s*1\.2")
        weapon = (ROOT/"Weapons"/"ScoutGun.lua").read_text(encoding="utf-8")
        self.assertIn('"30mm Autocannon"', weapon)
        script = (ROOT/"Scripts"/"scoutscript.lua").read_text(encoding="utf-8")
        self.assertIn('include("wheel_animation.lua")', script)
        self.assertIn('include("scout_rig_data.lua")', script)

    def test_low_poly_budget_counts_instances(self):
        count = sum(len(p["indices"]) for p in self.pieces.values())
        self.assertEqual(count, self.manifest["triangles"])
        self.assertLessEqual(count, 2400)
        self.assertGreater(count, 1200)
        glb_count = sum(len(read_accessor(self.gltf, self.binary,
                        self.gltf["meshes"][n["mesh"]]["primitives"][0]["indices"]))//3
                        for n in self.nodes.values() if "mesh" in n)
        self.assertEqual(glb_count, count)

    def test_six_wheel_rig_and_nested_weapon_pivots(self):
        expected = {"Base", "Turret", "Gun", "Flare"}
        for label in ("L", "R"):
            for i in range(1, 4):
                expected.add(f"Wheel{label}{i}")
        self.assertEqual(set(self.pieces), expected)
        self.assertEqual(len(self.pieces), 10)
        self.assertEqual(self.pieces["Turret"]["parent"], "Base")
        self.assertEqual(self.pieces["Gun"]["parent"], "Turret")
        self.assertEqual(self.pieces["Flare"]["parent"], "Gun")
        for label in ("L", "R"):
            for i in range(1, 4):
                self.assertEqual(self.pieces[f"Wheel{label}{i}"]["parent"], "Base")
        self.assertGreater(self.pieces["Flare"]["position"][2], 18)
        # All six wheels must share one mesh instance; instance cost still counts six.
        wheel_meshes = {self.nodes[f"Wheel{label}{i}"]["mesh"]
                        for label in ("L", "R") for i in range(1, 4)}
        self.assertEqual(len(wheel_meshes), 1)
        self.assertEqual(len(self.pieces["WheelL1"]["indices"]), 48)

    def test_bounds_ground_clearance_and_proportions(self):
        points = np.concatenate([p["vertices"][:, :3]+p["position"]
                                 for p in self.pieces.values() if len(p["vertices"])])
        low, high = points.min(axis=0), points.max(axis=0)
        self.assertAlmostEqual(low[1], 0.0, places=4)   # tyres touch the ground
        self.assertLess(high[1], 36)                    # sensor mast, not a tower
        self.assertGreater(high[0]-low[0], 30)
        self.assertLess(high[0]-low[0], 34)
        self.assertGreater(high[2]-low[2], 50)
        self.assertLess(high[2]-low[2], 56)
        # Hull sits above the wheel centres: this is a high-clearance 6x6.
        hull = self.pieces["Base"]
        hull_low = (hull["vertices"][:, 1] + hull["position"][1]).min()
        self.assertGreater(hull_low, 5.0)
        np.testing.assert_allclose(low, self.manifest["bounds"]["min"], atol=4e-6)
        np.testing.assert_allclose(high, self.manifest["bounds"]["max"], atol=4e-6)
        self.assertLess(np.linalg.norm(points-np.asarray(self.header[4:7]), axis=1).max(),
                        self.header[2]+1e-4)

    def test_native_and_glb_match_source(self):
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
            self.assertEqual(primitive["mode"], 4)
            for field, columns in (("POSITION", slice(0, 3)), ("NORMAL", slice(3, 6)),
                                   ("TEXCOORD_0", slice(6, 8))):
                actual = read_accessor(self.gltf, self.binary, primitive["attributes"][field])
                np.testing.assert_array_equal(actual, v[:, columns])
            np.testing.assert_array_equal(read_accessor(self.gltf, self.binary, primitive["indices"]),
                                          piece["indices"].ravel())
            np.testing.assert_allclose(v[:, :3], mesh.positions, atol=2e-6)
            np.testing.assert_allclose(v[:, 3:6], mesh.normals, atol=1e-6)

    def test_hard_normals_and_valid_geometry(self):
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

    def test_flat_palette_and_s3o_channel_contract(self):
        self.assertEqual(self.textures, ["scout_diffuse.tga", "scout_material.tga"])
        diffuse = Image.open(ROOT/"UnitTextures"/self.textures[0]).convert("RGBA")
        material = Image.open(ROOT/"UnitTextures"/self.textures[1]).convert("RGBA")
        self.assertEqual(diffuse.size, (256, 256))
        self.assertEqual(material.size, diffuse.size)
        for name, rgb in builder.COLORS.items():
            x0, y0, x1, y1 = builder.RECTS[name]
            colors = diffuse.crop((x0, y0, x1, y1)).getcolors()
            self.assertEqual(len(colors), 1, "No noisy photographic or camouflage swatches")
            expected = rgb+(255 if name == "team" else 0,)
            self.assertEqual(colors[0][1], expected)
            self.assertEqual(material.getpixel((x0, y0))[3], 255)
        self.assertEqual(material.getchannel("R").getextrema(), (0, 0))
        # The stencil cell is deliberately multi-colour; the vent cell is not a swatch.
        self.assertGreater(len(diffuse.crop(builder.RECTS["mark"]).getcolors()), 1)

    def test_glb_embeds_the_visibility_texture(self):
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
        self.assertIn("FV-6", self.gltf["asset"]["generator"])
        for view in self.gltf["bufferViews"]:
            self.assertEqual(view.get("byteOffset", 0) % 4, 0)
            self.assertLessEqual(view.get("byteOffset", 0)+view["byteLength"], len(self.binary))

    def test_script_piece_names_all_exist_in_the_model(self):
        script = (ROOT/"Scripts"/"scoutscript.lua").read_text(encoding="utf-8")
        names = set(re.findall(r'piece\s+"([^"]+)"', script))
        rig = (ROOT/"Scripts"/"scout_rig_data.lua").read_text(encoding="utf-8")
        names |= set(re.findall(r'"(Wheel[LR]\d)"', rig))
        self.assertEqual(names, set(self.pieces))
        self.assertEqual(rig.count('"WheelL'), 3)
        self.assertEqual(rig.count('"WheelR'), 3)

    def test_existing_units_and_starting_sides_are_untouched(self):
        for name in ("m1a1.s3o", "m1a1.glb", "ztz99a.s3o", "MBT.glb"):
            self.assertTrue((ROOT/"Objects3d"/name).is_file())
        side = (ROOT/"GameData"/"SideData.lua").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'startUnit\s*=\s*"([^"]+)"', side), ["mbt", "m1a1"])

    def test_icon_is_ready_to_use(self):
        image = Image.open(ROOT/"UnitPics"/"scout.png")
        self.assertEqual(image.size, (256, 256))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
        for name in ("scout_front.png", "scout_rear.png", "scout_views.png"):
            self.assertTrue((ROOT/"tools"/"previews"/name).is_file())


if __name__ == "__main__":
    unittest.main()
