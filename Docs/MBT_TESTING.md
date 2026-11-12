# MBT 本地测试

新增的低模 M1A1 使用独立的 [Test-M1.bat](../Test-M1.bat)，详见 [M1A1 测试说明](M1A1_TESTING.md)。本文的原 99A 场景保持不变。

## 直接开始

双击游戏目录中的 [Test-MBT.bat](../Test-MBT.bat)。不需要安装 Python 或建模软件。

- 地图：本机已有的 **Low Poly Plains v2**。
- 玩家控制蓝队 MBT，红队由本机已有的 **NullAI 0.1** 托管。
- 如果停在准备界面，按 Enter 打开聊天，输入 `/forcestart` 开始。
- 左键选择坦克，右键地面移动，右键敌方坦克攻击；滚轮缩放视角。
- 这是测试场景：没有基地建设链，消灭对方不会自动结束测试。退出游戏后重新打开启动入口可以重置场景。

NullAI 不会主动下达移动、生产等指令，适合测试模型、移动和武器。**它不等于关闭单位武器或自动行为**：红队坦克接敌后仍可能按引擎默认行为自动还击或短距离追击。

启动器使用 Recoil 根目录下独立的 `.mygame-test` 写入目录，并且只进行本地运行。日志、截图和测试设置存放在那里，不改原来的 `_script.txt` 或根目录的 `springsettings.cfg`。再次启动时会保留已有测试设置。

## 为什么暂时不用 BARb

之前的日志显示，BARb 在游戏资源与 AI 资源中都没有找到所需的 `init.as`，初始化后被移除。选择 AI 名称不等于完成对 MyGame 的适配。当前只是测试坦克，先使用已有的 NullAI 即可，不必为了查看模型而安装一整套战略 AI。

## 新模型文件

| 文件 | 用途 |
| --- | --- |
| [ztz99a.s3o](../Objects3d/ztz99a.s3o) | 游戏实际使用的原生模型 |
| [ztz99a.glb](../Objects3d/ztz99a.glb) | 含内嵌贴图的交换文件，可导入支持 glTF 的编辑器 |
| [ztz99a_diffuse.tga](../UnitTextures/ztz99a_diffuse.tga) | 数字迷彩、编号、徽记与队色遮罩 |
| [ztz99a_material.tga](../UnitTextures/ztz99a_material.tga) | 反射、发光与贴花透明遮罩 |
| [ztz99a.png](../UnitPics/ztz99a.png) | 单位图标 |
| [build_ztz99a.py](../tools/build_ztz99a.py) | 可修改、可重新生成的建模源代码 |
| [track_animation.lua](../Scripts/track_animation.lua) | 按实际位移和转向驱动履带、负重轮及端轮 |
| [track_motion.lua](../Scripts/track_motion.lua) | 闭合路径与左右差速计算 |
| [ztz99a_track_data.lua](../Scripts/ztz99a_track_data.lua) | 生成器输出的履带尺寸、初始位置和角度 |

模型参考 99A 的外形特征制作，不是精确比例复刻或工程模型。包含楔形炮塔、炮管热护套和抽烟装置、分块装甲和侧裙、六对负重轮、逐节履带、烟幕发射器、观察设备、车顶机枪、后部篮架及双油桶。车顶机枪是装饰部件，不新增武器位。

模型使用 **X 向右、Y 向上、Z 向前**。保留原有 `Base → Turret → Gun → Flare` 和 12 个负重轮，另拆出每侧 84 个履带节以及 4 个端轮，共 188 个节点。分件没有增加三角面数量，外形和贴图保持不变。

履带节现在会沿闭合路径实际移动，不是贴图滑动：前进和反向位移时方向相反，转弯时左右差速，停车时停止并保持当前相位。负重轮和端轮的转速同步匹配各侧履带。驱动读取模拟帧中的真实位移与朝向，暂停游戏或车辆卡住时不会凭计时器空转。

车体不再叠加固定周期的上下弹跳，也不在模型根节点重复施加地形倾斜。`Upright=false` 保留引擎的地面随动，`UpDirSmoothing=0.95` 把响应放到最慢（引擎上限 0.95），过台阶时车体约 1 秒才跟到位。注意引擎的地面随动**没有倾角上限**（`GetWantedUpDir` 只做插值），最终仍会跟到坡角。行驶速度、加速度、刹车参数和武器数值没有因此改变。

这不改变车辆原有寻路或驾驶规则，也不新增倒车按键。如果寻路选择掉头，看到的是对应的差速转向。GLB 保留完整分件，但动画由 Recoil 的 Lua 脚本驱动，单独打开 GLB 不会自动播放履带。

旧的 [MBT.glb](../Objects3d/MBT.glb)、[MBT.lua](../Objects3d/MBT.lua) 和 [MBTtexture.tga](../UnitTextures/MBTtexture.tga) 仍保留。旧模型不包含这些履带分件，不能只把 `ObjectName` 改回旧模型而继续使用当前滚动脚本；回退时也需要恢复与旧模型对应的单位脚本。

## 预览与重新生成

- [正面三分之四视角](../tools/previews/ztz99a_front.png)
- [后侧视角](../tools/previews/ztz99a_rear.png)
- [侧视图](../tools/previews/ztz99a_side.png)

以上是同一份模型数据生成的离线预览，不是引擎截图；游戏中的照明会有所不同。另附[未经修改的实机截图](../tools/previews/ztz99a_ingame.png)。

从 Recoil 工作区运行：

```sh
python -I games/MyGame.sdd/tools/build_ztz99a.py
```

生成器需要 Python 3.10+、Pillow 和 NumPy。它会重建新模型、贴图、图标和预览，不会覆盖旧 MBT 资源。不要在游戏正在加载这些文件时重新生成。

## 检查命令

```sh
python -I games/MyGame.sdd/tools/test_ztz99a.py
python -I games/MyGame.sdd/tools/test_ui_loading.py
python -I games/MyGame.sdd/tools/test_tracks.py
python -I games/MyGame.sdd/tools/smoke_mbt.py
python -I games/MyGame.sdd/tools/smoke_tracks.py
```

UI 与履带逻辑测试使用 `lupa.lua51`。如果 lupa 装在隔离目录，给相应的 Lua 测试命令追加 `--lua-path <安装目录>`，不需要改游戏代码。

实际引擎检查会打开独立的本地窗口，使用单独的近距目标布局，选择坦克、下达移动和攻击指令、截图，然后退出。检查会断言模型部件、移动、武器发射和受伤事件，而不是只看进程是否正常退出。近距布局用于避免测试点之间的地形遮挡；不会改变上述手动测试场景。它打印临时输出目录，内含 `infolog.txt`、`report.json` 和截图；不会操作已有引擎进程。

履带专项检查会在临时目录生成一个依赖 MyGame 的测试游戏，不改真实游戏文件。先检查正常移动和停车，再仅在测试场景中用 MoveCtrl 驱动反向位移和原地转向；它读回实际履带节位置及矩阵，断言运动方向、停转、闭合路径、部件朝向和车体根节点的稳定性，并保存两张检查截图。如果显卡驱动在加载时卡住，可给这条测试命令追加 `--safe-mode` 使用独立的保守渲染设置，主游戏配置不受影响。高频截图录制在本机触发过驱动挂起，因此不作为该测试的依赖。

这些启动和验证流程已经保存在工具脚本中。若以后希望固化为项目专用运行技能，可使用 `/run-skill-generator`；正常双击测试不需要这一步。

两个开局 UI 脚本已从 `LuaRules/Gadgets` 移到 `LuaUI/Widgets`。开始区域显示只在手选出生位置的模式启用；固定起点测试中跳过该组件是正常行为，不是再次加载失败。
