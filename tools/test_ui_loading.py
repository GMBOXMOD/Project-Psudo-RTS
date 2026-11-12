"""Exercise the real UI source in Lua 5.1 using directory-specific environments.

Install lupa separately; --lua-path can point to an isolated installation. This
checks loading and selection/start-box initialization, not OpenGL rendering.
"""

import argparse
import pathlib
import sys
import unittest


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--lua-path", type=pathlib.Path)
args, remaining = parser.parse_known_args()
if args.lua_path:
    sys.path.insert(0, str(args.lua_path.resolve()))
from lupa.lua51 import LuaRuntime

GAME = pathlib.Path(__file__).resolve().parents[1]
NAMES = ("gui_center_n_select.lua", "map_startbox.lua")
ENVIRONMENT = r'''
function environment(kind, startPosType)
    local noop = function() end
    local font = setmetatable({}, {__index=function() return noop end})
    local env = {
        Game={startPosType=startPosType, mapSizeX=4096, mapSizeZ=4096},
        LUAUI_DIRNAME="LuaUI/", WG={},
        GL=setmetatable({}, {__index=function() return 0 end}),
        widgetHandler={RemoveWidget=noop, DisableWidget=noop, EnableWidget=noop},
    }
    env[kind] = {}
    env.gl = setmetatable({
        LoadFont=function() return font end,
        CreateList=function(fn) fn(); return 1 end,
        BeginEnd=function(_, fn) fn() end,
    }, {__index=function() return noop end})
    env.Spring = setmetatable({
        GetConfigString=function(_, default) return default end,
        GetConfigInt=function(_, default) return default end,
        GetViewGeometry=function() return 1280, 800 end,
        GetGameFrame=function() return 0 end,
        GetGameSeconds=function() return 1 end,
        GetSpectatingState=function() return false end,
        IsReplay=function() return false end,
        GetTimer=function() return 0 end,
        GetMyTeamID=function() return 0 end,
        GetMyPlayerID=function() return 0 end,
        GetMyAllyTeamID=function() return 0 end,
        GetGaiaTeamID=function() return 2 end,
        GetTeamList=function() return {0,1,2} end,
        GetAllyTeamList=function() return {0,1,2} end,
        GetPlayerInfo=function() return "Tester", true, false end,
        GetTeamInfo=function(id) return id, 0, false, false, "Beefys", id end,
        GetTeamUnits=function() return {42} end,
        GetUnitPosition=function() return 100, 20, 200 end,
        GetGroundExtremes=function() return 0, 100 end,
        GetAllyTeamStartBox=function() return 1000,1000,2000,2000 end,
        SelectUnitArray=function(units) env.selected=units[1] end,
        SetCameraTarget=function(x,y,z) env.camera={x,y,z} end,
    }, {__index=function() return noop end})
    setmetatable(env, {__index=_G})
    env._G = env
    return env
end
function loadSource(source, filename, env)
    local chunk, err = loadstring(source, filename)
    assert(chunk, err)
    setfenv(chunk, env)
    return chunk()
end
'''


class WidgetLoadingTests(unittest.TestCase):
    def load_widget(self, name, start_pos_type):
        matches = list((GAME / "LuaRules" / "Gadgets").glob(name))
        matches += list((GAME / "LuaUI" / "Widgets").glob(name))
        self.assertEqual(len(matches), 1, "Expected exactly one loadable copy")
        path = matches[0]
        kind = "gadget" if path.parent.name == "Gadgets" else "widget"
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(ENVIRONMENT)
        env = lua.globals().environment(kind, start_pos_type)
        result = lua.globals().loadSource(path.read_text(encoding="utf-8"), str(path), env)
        self.assertEqual(kind, "widget", "UI scripts must be loaded by LuaUI")
        return lua, env, result

    def test_fixed_start_loading(self):
        for name in NAMES:
            with self.subTest(widget=name):
                _, _, result = self.load_widget(name, 3)
                if name == "map_startbox.lua":
                    self.assertIs(result, False, "Start boxes should skip fixed-position games")

    def test_choose_start_loading_and_initialization(self):
        for name in NAMES:
            with self.subTest(widget=name):
                _, env, _ = self.load_widget(name, 2)
                widget = env.widget
                self.assertTrue(widget.GetInfo(widget).enabled)
                if widget.Initialize:
                    widget.Initialize(widget)

    def test_player_tank_is_selected_and_centered(self):
        _, env, _ = self.load_widget("gui_center_n_select.lua", 3)
        env.widget.Update(env.widget)
        self.assertEqual(env.selected, 42)
        self.assertEqual(list(env.camera.values()), [100, 20, 200])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + remaining)
