# M1A1 低模测试

## 直接查看

双击 [Test-M1.bat](../Test-M1.bat)。无需安装 Python 或建模软件。

- 蓝队由玩家控制 **M1A1 Abrams**；红队仍是现有 **ZTZ-99A**，便于对照。
- 地图为 **Low Poly Plains v2**，对手由本机已有的 **NullAI 0.1** 托管。
- 准备界面如果没有自动开始，按 Enter 输入 `/forcestart`。
- 左键选择，右键地面移动，右键敌方坦克攻击，滚轮缩放。
- NullAI 不下达战略指令，但单位仍可能自动还击或短距离追击。

这是独立测试入口，不增加基地建设链，也不改变原 [Test-MBT.bat](../Test-MBT.bat) 的两辆 99A 场景。新增的 `Abrams` 测试阵营以 `m1a1` 开局；原 `Beefys` 仍以 `mbt` 开局。

设置、日志和截图写入 Recoil 根目录下的 `.mygame-m1-test`，与原 `.mygame-test` 分开；不覆盖根目录的游戏配置或 `_script.txt`。更新资源后需要退出当前对局，再开一局才能加载。

## 模型与风格

本次外观已整理为后续机械、生物单位及 RTS 建筑共用的[单位与建筑建模风格指南](UNIT_MODELING_STYLE.md)，并附有[固定 M1A1 基准档案](UnitStyle/M1A1_BASELINE.md)与项目内 `unit-model-style` skill。下文保留该坦克自身的资源、参数和测试说明。

外形参照提供的 **M1A1 Abrams 1991** 多视图，细节密度参照另一张低模坦克图：沙色平涂、硬边法线、大块面，不堆叠螺栓、细网格和迷彩噪点。保留低矮车体、倾斜炮塔前脸、长尾舱、120mm 炮管的抽烟装置、七对负重轮、侧裙和简化车顶设备。模型和贴图均由生成器原创构建，不使用参考图片作为贴图。

- **3,058 个三角面**，包括两侧所有履带节和轮子，不是只计算去重后的网格。
- 相比现有 99A 的 36,168 面，减少约 **92%**；生成器限制在 3,200 面以内。
- 两张 **256 × 256** 原生贴图；GLB 内嵌可见性贴图。
- **102 个节点**：车体、炮塔、炮管、炮口，14 个负重轮，4 个端轮，80 个履带节。
- 这是游戏用的简化外形，不是精确比例的工程模型；机枪和烟幕装置仅作装饰。

[前侧预览](../tools/previews/m1a1_front.png) · [后侧预览](../tools/previews/m1a1_rear.png) · [三视图](../tools/previews/m1a1_views.png)

以上是同一模型的离线渲染，实际引擎的光照不同。另附[未经修改的实机移动截图](../tools/previews/m1a1_ingame.png)。

## 动画与游戏接入

炮塔可旋转，主炮可俯仰并带后坐。每侧 40 个简化履带节沿闭合路径滚动，按实际位移计算前进、反向位移和左右差速；停车后保持履带相位。GLB 保留分件和枢轴，动画由游戏 Lua 驱动，单独打开 GLB 不会自动播放。

M1 与 99A 共用 [track_animation.lua](../Scripts/track_animation.lua) 的参数化控制器，但各自传入自己的履带尺寸和轮子数量，不共用运动状态。车体不叠加周期弹跳；使用 `Upright=false` 和 `UpDirSmoothing=0.95` 跟随真实地面。引擎把该值钳在 `[0, 0.95]`，0.95 是最慢响应，跨台阶时车体约 1 秒才倒到位，不会瞬间掀翻。注意引擎的地面随动**没有倾角上限**（`GetWantedUpDir` 只做插值），最终仍会跟到坡角。未新增倒车键，也未修改寻路规则。

测试阶段沿用现有 MBT 的生命值、移动和武器伤害数值。M1 使用独立的 120mm 武器名称，不修改 99A 的 125mm 武器；另有独立的无伤害死亡特效，不产生冲击力或地形坑洞。现有 99A、旧 MBT 模型与贴图均保留。

## 可编辑资源

| 文件 | 用途 |
| --- | --- |
| [m1a1.s3o](../Objects3d/m1a1.s3o) | 游戏实际使用的原生模型 |
| [m1a1.glb](../Objects3d/m1a1.glb) | 带内嵌贴图的 glTF 交换模型 |
| [build_m1a1.py](../tools/build_m1a1.py) | 几何、配色、分件和预览的生成源代码 |
| [m1a1_diffuse.tga](../UnitTextures/m1a1_diffuse.tga) | 沙色、标记和小面积队色遮罩 |
| [m1a1_material.tga](../UnitTextures/m1a1_material.tga) | 反射和贴花可见性遮罩 |
| [m1a1_track_data.lua](../Scripts/m1a1_track_data.lua) | 生成的履带几何参数；不要手工改 |
| [m1a1script.lua](../Scripts/m1a1script.lua) | 单位动画 |
| [m1a1.lua](../Units/m1a1.lua) | 单位定义 |

坐标为 **X 向右、Y 向上、Z 向前**。S3O 没有静态旋转字段，因此履带节初始转角烘焙进顶点和法线；不要只改节点位置而忽略生成的初始角度。

从 Recoil 工作区重新生成：

```sh
python -I games/MyGame.sdd/tools/build_m1a1.py
```

需要 Python 3.10+、NumPy、Pillow，与 99A 生成器相同。M1 复用原生成器的基础图元、导出和离线渲染函数，但使用独立的模型与颜色表。该命令只写 M1 资源，不重建 99A；不要在游戏加载这些文件时重新生成。

## 验证

```sh
python -I games/MyGame.sdd/tools/test_m1a1.py
python -I games/MyGame.sdd/tools/test_tracks.py --model m1a1
python -I games/MyGame.sdd/tools/smoke_mbt.py --model m1a1 --safe-mode
python -I games/MyGame.sdd/tools/smoke_tracks.py --model m1a1 --safe-mode
```

Lua 测试需要 `lupa.lua51`。若它安装在隔离目录，给 `test_tracks.py` 追加 `--lua-path <安装目录>`。

模型检查覆盖三角面预算、七轮分件、硬边法线、S3O/GLB 对应、贴图通道、履带完整路径和原模型保留。两个实机检查会启动并操作真正的 Recoil 窗口，检查单位类型、移动、开炮与伤害，或读取实际履带矩阵验证前进、停车、反向位移、原地转向和车体稳定。仅专项测试的反向/转向阶段使用 MoveCtrl。

实机检查在新的临时目录写入配置、日志、报告和稀疏截图，结束后只关闭自己启动的客户端，不操作已有游戏进程。`--safe-mode` 只作用于该次隔离检查。不录制高频截图或 GIF，避免本机之前出现的显卡驱动挂起。

省略 `--model m1a1` 时，原履带与实机检查仍默认测试 99A。
