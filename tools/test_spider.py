"""Validate the SP-6 Engineer asset, gait contract and native/exchange exports."""

import io
import json
import pathlib
import re
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_spider as builder
from test_ztz99a import load_glb, load_s3o, read_accessor

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SpiderModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header, cls.pieces, cls.textures = load_s3o(ROOT/"Objects3d"/"spider.s3o")
        cls.gltf, cls.binary = load_glb(ROOT/"Objects3d"/"spider.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}
        cls.manifest = json.loads((ROOT/"tools"/"previews"/"spider_manifest.json").read_text(encoding="utf-8"))
        cls.generated = {p.name: p for p, _ in builder.walk(builder.make_model())}
        cls.posed = builder.posed_for_preview(builder.make_model())
        cls.rig = (ROOT/"Scripts"/"spider_rig_data.lua").read_text(encoding="utf-8")

    def test_builder_unit_definition(self):
        unit = (ROOT/"Units"/"spider.lua").read_text(encoding="utf-8")
        for field, value in (("ObjectName", "spider.s3o"), ("script", "spiderscript.lua"),
                             ("BuildPic", "spider.png"), ("MovementClass", "spider3x3")):
            self.assertRegex(unit, rf'{field}\s*=\s*"{re.escape(value)}"')
        self.assertRegex(unit, r"Builder\s*=\s*true")
        self.assertRegex(unit, r"WorkerTime\s*=\s*6")
        self.assertRegex(unit, r"BuildDistance\s*=\s*120")
        self.assertRegex(unit, r"CanAttack\s*=\s*false")
        # Without a non-zero terraformSpeed the engine keeps the builder in the
        # terraform branch forever and UpdateBuild never runs -> 0% progress.
        self.assertRegex(unit, r"terraformSpeed\s*=\s*[1-9]")
        for option in ("extractor", "energyreactor", "llt", "factory"):
            self.assertIn(f'"{option}"', unit)
        self.assertNotIn("weapons", unit.lower())
        moves = (ROOT/"GameData"/"MoveDefs.lua").read_text(encoding="utf-8")
        self.assertIn('"spider3x3"', moves)
        block = moves.split('"spider3x3"', 1)[1]
        # Raised to 90 so the six legs can climb the terraced low-poly map.
        self.assertRegex(block, r"maxSlope\s*=\s*90")

    def test_low_poly_budget_counts_instances(self):
        count = sum(len(p["indices"]) for p in self.pieces.values())
        self.assertEqual(count, self.manifest["triangles"])
        self.assertLessEqual(count, 3200)
        self.assertGreater(count, 1200)
        glb_count = sum(len(read_accessor(self.gltf, self.binary,
                        self.gltf["meshes"][n["mesh"]]["primitives"][0]["indices"]))//3
                        for n in self.nodes.values() if "mesh" in n)
        self.assertEqual(glb_count, count)

    def test_six_legs_and_two_construction_arms(self):
        expected = {"Base"}
        for label in ("L", "R"):
            for i in range(1, 4):
                expected.update({f"Hip{label}{i}", f"Knee{label}{i}"})
            expected.update({f"Arm{label}", f"Forearm{label}", f"Nano{label}"})
        self.assertEqual(set(self.pieces), expected)
        self.assertEqual(len(self.pieces), 19)
        for label in ("L", "R"):
            for i in range(1, 4):
                self.assertEqual(self.pieces[f"Hip{label}{i}"]["parent"], "Base")
                self.assertEqual(self.pieces[f"Knee{label}{i}"]["parent"], f"Hip{label}{i}")
            self.assertEqual(self.pieces[f"Arm{label}"]["parent"], "Base")
            self.assertEqual(self.pieces[f"Forearm{label}"]["parent"], f"Arm{label}")
            self.assertEqual(self.pieces[f"Nano{label}"]["parent"], f"Forearm{label}")
        # Nano emitters are logical points, not visible geometry.
        self.assertFalse(len(self.pieces["NanoL"]["vertices"]))

    def test_bounds_feet_on_ground(self):
        # The exported tree is the canonical leg; bounds describe the splayed pose.
        points = np.concatenate([np.asarray(p.mesh.positions) + off
                                 for p, off in builder.walk(self.posed) if p.mesh])
        low, high = points.min(axis=0), points.max(axis=0)
        self.assertAlmostEqual(low[1], 0.0, places=4)
        self.assertGreater(high[0]-low[0], 55)
        self.assertLess(high[0]-low[0], 64)
        self.assertGreater(high[2]-low[2], 38)
        self.assertLess(high[2]-low[2], 45)
        self.assertLess(high[1], 26)
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
        self.assertEqual(self.textures, ["spider_diffuse.tga", "spider_material.tga"])
        diffuse = Image.open(ROOT/"UnitTextures"/self.textures[0]).convert("RGBA")
        material = Image.open(ROOT/"UnitTextures"/self.textures[1]).convert("RGBA")
        self.assertEqual(diffuse.size, (256, 256))
        for name, rgb in builder.COLORS.items():
            x0, y0, x1, y1 = builder.RECTS[name]
            colors = diffuse.crop((x0, y0, x1, y1)).getcolors()
            self.assertEqual(len(colors), 1, "No noisy photographic swatches")
            self.assertEqual(colors[0][1], rgb+(255 if name == "team" else 0,))
            self.assertEqual(material.getpixel((x0, y0))[3], 255)
        self.assertEqual(material.getchannel("R").getextrema(), (0, 0))
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
        self.assertIn("SP-6", self.gltf["asset"]["generator"])

    def test_rig_data_matches_the_model_and_tripod_phases(self):
        hips = re.findall(r'hip = "(Hip[LR]\d)"', self.rig)
        knees = re.findall(r'knee = "(Knee[LR]\d)"', self.rig)
        self.assertEqual(len(hips), 6)
        self.assertEqual(len(knees), 6)
        self.assertEqual(set(hips) | set(knees), {p for p in self.pieces if p != "Base"}
                         - {"ArmL", "ArmR", "ForearmL", "ForearmR", "NanoL", "NanoR"})
        phases = re.findall(r"phase = (0\.5|0\.0)", self.rig)
        self.assertEqual(len(phases), 6)
        self.assertEqual(phases.count("0.0"), 3)
        self.assertEqual(phases.count("0.5"), 3)
        self.assertRegex(self.rig, r"stride = 18")
        script = (ROOT/"Scripts"/"spiderscript.lua").read_text(encoding="utf-8")
        self.assertIn('include("spider_gait.lua")', script)
        self.assertIn("QueryNanoPiece", script)
        self.assertIn("StartBuilding", script)
        for piece in ("ArmL", "ArmR", "ForearmL", "ForearmR", "NanoL", "NanoR"):
            self.assertIn(f'piece "{piece}"', script)

    def test_generated_gait_data_matches_the_editable_source(self):
        with tempfile.TemporaryDirectory(prefix="spider-rig-test-") as folder:
            path = pathlib.Path(folder)/"spider_rig_data.lua"
            builder.write_rig_data(path)
            self.assertEqual(path.read_text(encoding="utf-8"), self.rig)
        self.assertEqual(self.generated["KneeR2"].offset, (*builder.KNEE, 0))
        self.assertGreater(builder.STANCE_FRACTION, 0.5)
        self.assertLess(builder.STANCE_FRACTION, 1)

    def test_existing_units_and_starting_sides_are_untouched(self):
        for name in ("m1a1.s3o", "scout.s3o", "ztz99a.s3o", "MBT.glb"):
            self.assertTrue((ROOT/"Objects3d"/name).is_file())
        side = (ROOT/"GameData"/"SideData.lua").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'startUnit\s*=\s*"([^"]+)"', side), ["mbt", "m1a1"])

    def test_icon_is_ready_to_use(self):
        image = Image.open(ROOT/"UnitPics"/"spider.png")
        self.assertEqual(image.size, (256, 256))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
        for name in ("spider_front.png", "spider_rear.png", "spider_views.png"):
            self.assertTrue((ROOT/"tools"/"previews"/name).is_file())


if __name__ == "__main__":
    unittest.main()
