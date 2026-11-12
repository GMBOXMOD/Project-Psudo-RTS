# FV-6 Scout · 交付记录

> 首个按 [M1A1 基准](../UNIT_MODELING_STYLE.md) 制作的轮式单位。本文只记录本次任务的范围、实际预算与验证状态，不复制通用规范。

## A. 任务

| 项 | 内容 |
| --- | --- |
| 单位 | `scout` / **FV-6 Scout**，六轮装甲侦察车 |
| 类型 | 新建，机械分支（[MECHANICAL](../UnitStyle/MECHANICAL.md)） |
| 产物 | 生成器、S3O、GLB、两张原生贴图、图标、预览、单位脚本、武器、静态测试 |
| 可改范围 | 仅新增文件；未改动 mbt / m1a1 / ztz99a / MBT 及任何既有数值 |
| 标准版本 | M1A1 基准 · 平涂块面低模 v1 |
| 例外 | 无。冷灰蓝涂装属于"新单位自己决定"，不改变风格标准 |

## B. 设计与实现

### 识别锚点

1. **六个大直径轮**，三轴等距，胎面在俯视角下露出挡泥板外——这是 RTS 视角下唯一的六轮读数。
2. **高窄车体 + 倾斜首上**，与两辆坦克的低矮楔形形成对比。
3. **小型遥控炮塔 + 细长机炮**，明显小于主战坦克炮塔。
4. **车顶传感器桅杆**，侦察定位的功能特征。

### 形体与颜色

- 一级：车体、炮塔；二级：六轮、机炮、桅杆、挡泥板；三级：观察窗、烟幕发射器、天线、尾门标记。
- 明确省略：螺栓、铆钉、装甲块、履带式细节、照片纹理。
- 调色板 14 个语义色：主体 / 亮 / 暗 / 边缘、橡胶、轮毂、黑、玻璃、深玻璃、钢、灯、红、队色、帆布。
- 队色只出现在**挡泥板顶面**与炮塔尾板，俯视可读，不覆盖主体。

### 技术契约

| 项 | 值 |
| --- | --- |
| 坐标 | X 右、Y 上、Z 前（与 S3O 一致） |
| 层级 | `Base → Turret → Gun → Flare`；`WheelL1-3` / `WheelR1-3` 挂在 `Base` |
| 节点 | 10（6 个轮子共享同一 mesh） |
| 三角面 | **1,738**（生成器上限 2,400） |
| 贴图 | 两张 256×256 RGBA TGA；贴图 1 的 A = 队色遮罩，贴图 2 的 R=0 / G=反射 / A=可见性 |
| 包围盒 | 32.5 × 33.0 × 53.35（含桅杆与天线） |
| 碰撞体 | `33 20 52`，偏移 `0 16 0`——排除桅杆与天线 |
| 转向 | `TurnInPlace = false`、`TurnInPlaceSpeedLimit = 1.2`——轮式底盘不掉头原地转，转弯时保持约 1/3 最高速 |
| 动画 | 刚性分件；轮速由**实际位移**驱动（复用 `track_motion.lua` 的差速数学），无二次车体倾斜或周期弹跳 |

## C. 验证记录

| 阶段 | 检查 | 状态 | 证据 |
| --- | --- | --- | --- |
| A | 静态资产（预算、节点、法线、UV、通道、包围体、源/原生/交换一致） | **PASS** | `python -I games/MyGame.sdd/tools/test_scout.py` → **11 项通过** |
| B | 单位脚本实例化 | **PASS** | 无渲染启动，临时插桩输出 `[Scout] Create ran, wheels=3`，插桩已还原 |
| B | 单位定义解析与创建 | **PASS** | `[MyGame] 队伍 0 造出了 scout`，零 Lua 报错 |
| C | 实机外观（引擎内） | **PASS** | `tools/previews/scout_ingame.png`（1920×1080 实机截图）与 `scout_ingame_crop.png` |
| C | 实机转向行为 | **PASS** | 见下方"转向实测" |
| C | 开火 / 后坐动画 | **NOT_RUN** | 本次未在实机开火 |

### 实机外观

引擎内确认：模型正立、朝向正确、六轮接地、队色可见、无缺面或穿插。采样像素与调色板一致——车体顶面 `(115,130,137)`、挡泥板 `(136,151,157)`、后甲板 `(84,97,104)`，没有出现光照冲白。

### 转向实测

用临时 gadget 给一辆静止的 scout 下达反方向移动指令，每 3 帧记录速度与朝向：

```text
f= 99  speed=1.200  dirz=-0.944
f=120  speed=1.200  dirz=-0.391
f=150  speed=1.195  dirz=+0.721
f=156  speed=1.200  dirz=+0.866
```

180° 掉头全程速度恒定在 **1.200 elmo/帧（36 elmo/s）**，没有降到 0。这同时确认了两件事：

- `TurnInPlace = false` 生效：不会停下来原地旋转。
- `TurnInPlaceSpeedLimit` 的单位是 **elmo/帧**（1.2 正好是最高速 3.6 的 1/3）。

> 离线预览不能替代实机截图；本节 C 行的证据来自本次实际启动的图形客户端。

## D. 文件

```text
tools/build_scout.py              生成器（几何、图集、S3O/GLB、预览、manifest）
tools/test_scout.py               静态资产测试（11 项）
tools/scout_test.txt              无渲染/实机测试用启动脚本
tools/previews/scout_*.png        预览与多视图
Objects3d/scout.s3o               游戏实际加载的模型
Objects3d/scout.glb               交换资产（不含游戏动画）
UnitTextures/scout_diffuse.tga    底色 + 队色遮罩
UnitTextures/scout_material.tga   自发光 / 反射 / 可见性
UnitPics/scout.png                256×256 构建图标
Units/scout.lua                   单位定义
Weapons/ScoutGun.lua              30mm 机炮
Scripts/scoutscript.lua           炮塔、俯仰、后坐
Scripts/scout_rig_data.lua        生成的轮组参数
Scripts/wheel_animation.lua       共享轮式控制器（可复用于后续轮式单位）
```

## E. 使用与限制

- **未加入任何阵营出生链或工厂建造列表**——按规范，造型任务不自动改动阵营与建造链。
- 手动测试：`/cheat` 后 `/give scout @2000,0,2000`（坐标必填）。
- 若要正式投产，需要单独确认：加入哪个工厂的 `buildoptions`、造价与定位、是否替换现有侦察手段。

## F. 重建

```sh
python -I games/MyGame.sdd/tools/build_scout.py      # 重建模型、贴图、预览、图标
python -I games/MyGame.sdd/tools/test_scout.py       # 静态检查
```

生成器覆盖写入 `scout.*` 与 `scout_rig_data.lua`；不触碰任何其他单位。
