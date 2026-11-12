# UnitDef 字段速查

> 依据：Recoil 引擎 `rts/Sim/Units/UnitDef.cpp` 的解析语句（2026-11 拉取的 master）。
> 「默认」列是源码里 `GetXxx("key", 默认)` 的第二个参数。
> 键名经 `lowerkeys()`，**大小写不敏感**；但 `ObjectName` 的文件名、`weapons` 里的武器名是大小写敏感的。
>
> 武器字段见 [WEAPONDEF_API.md](WEAPONDEF_API.md)。

## 0. 文件骨架

```lua
-- Units/mytank.lua
local unitName = "mytank"          -- 必须与文件名一致

local unitDef = {
    name        = "My Tank",       -- 界面显示名
    ObjectName  = "mytank.s3o",
    script      = "mytankscript.lua",
    Side        = "Abrams",
    Category    = "LAND TANK NOTAIR NOTSUB",
    BuildPic    = "mytank.png",

    MaxDamage   = 2400,
    BuildCostMetal = 600,
    BuildCostEnergy = 2400,
    BuildTime   = 600,

    MaxVelocity = 2.6,
    Acceleration = 0.12,
    BrakeRate   = 0.10,
    TurnRate    = 300,
    MovementClass = "3x3",
    FootprintX  = 3,
    FootprintZ  = 3,

    weapons = { [1] = { name = "MyGun" } },
}

return lowerkeys({ [unitName] = unitDef })
```

> 旧键名（`MaxDamage`、`BuildCostMetal`、`MaxVelocity`、`Acceleration`、`BrakeRate`）都是**遗留别名**，引擎仍然认，但新键是 `health`、`metalCost`、`speed`、`maxAcc`、`maxDec`。两者单位可能不同，见 §5。

---

## 1. 身份与显示

| 字段 | 默认 | 说明 |
|---|---|---|
| `name` | 内部名 | 界面显示名（`UnitDefs[x].name`） |
| `description` | 内部名 | 鼠标提示 |
| `ObjectName` | `""` | 模型文件（`.s3o` / `.glb`） |
| `script` | 单位名 + `.cob` | 单位脚本，**不写会去找 .cob** |
| `Category` | `""` | 空格分隔的分类串，编译成位掩码，决定谁能打它、`damage` 表怎么匹配 |
| `Side` | — | 阵营名，需与 `SideData.lua` 对应 |
| `TEDClass` | — | 遗留分类（`Vech`/`Building`/…），影响音效与移动提示 |
| `BuildPic` | `""` | 建造菜单图标 |
| `iconType` | `"default"` | 地图图标样式 |
| `customParams` | — | 自由挂载表，引擎不解析，给 gadget 读（见缓速武器配方） |

## 2. 生命与探测

| 字段 | 默认 | 说明 |
|---|---|---|
| `health`（别名 `MaxDamage`） | `100` | 血量，≤0 直接报错 |
| `SightDistance` | `0` | 地面视野半径 |
| `sightEmitHeight` | `20` | 视野发射高度 |
| `airSightDistance` | `1.5 × SightDistance` | 对空视野 |
| `RadarDistance` | `0` | 雷达半径 |
| `SonarDistance` | `0` | 声呐半径 |
| `radarDistanceJam` | `0` | 雷达干扰半径 |
| `sonarDistanceJam` | `0` | 声呐干扰半径 |
| `seismicDistance` | `0` | 地震探测半径 |
| `seismicSignature` | 自动（坦克/机甲 = √(mass/100)） | 被地震探测到的信号强度 |
| `stealth` | `false` | 对雷达隐身 |
| `sonarStealth` | `false` | 对声呐隐身 |
| `canCloak` | `cloakCost != 0` | 能否隐身 |
| `cloakCost` / `cloakCostMoving` | `0` / 同 `cloakCost` | 隐身的每秒耗电 |
| `initCloaked` | `false` | 出生即隐身 |
| `minCloakDistance` | `0` | 距敌多近自动现形 |
| `decloakOnFire` | `true` | 开火破隐 |

## 3. 经济

| 字段 | 默认 | 说明 |
|---|---|---|
| `metalCost`（别名 `BuildCostMetal`） | `0` | 造价金属 |
| `energyCost`（别名 `BuildCostEnergy`） | `0` | 造价能量 |
| `buildTime` | `100` | 建造工作量，见 §10 坑 2 |
| `metalStorage` / `energyStorage` | `0` | 存储上限 |
| `extractsMetal` | `0` | 采矿速率，>0 即金属提取器 |
| `energyMake` / `metalMake` | `0` | 固定产出（每秒） |
| `energyUse`（别名 `energyUpkeep`） | `0` | 持续耗电（每秒） |
| `metalUse`（别名 `metalUpkeep`） | `0` | 持续耗金属 |
| `makesMetal` | `0` | 电能转金属的产出 |
| `windGenerator` | `0` | 风力发电系数 |
| `tidalGenerator` | `0` | 潮汐发电系数 |
| `idleTime` | `600` | 闲置多少帧后触发 idle 行为 |
| `idleAutoHeal` | `10` | 闲置后每秒回血 |
| `autoHeal` | `0` | 无条件每秒回血 |

## 4. 建造

| 字段 | 默认 | 说明 |
|---|---|---|
| `Builder` | `false` | 是否建造者 |
| `WorkerTime` | `0` | 建造功率（**每秒**；引擎内部 ÷30 转每帧） |
| `BuildDistance` | `128`（最小 38） | 建造/协助距离 |
| `buildRange3D` | `false` | 距离是否按 3D 算 |
| `RepairSpeed` / `ReclaimSpeed` / `ResurrectSpeed` / `CaptureSpeed` | 均回落 `WorkerTime` | 各能力的功率 |
| `maxRepairSpeed` | `1e20` | 维修功率上限 |
| **`terraformSpeed`** | **回落 `WorkerTime`** | 平整地基的速度，见 §10 坑 1 |
| `CanBeAssisted` | `true` | 能否被协助建造 |
| `canAssist` | 同 `Builder` | 能否协助别人 |
| `canRepair` / `canReclaim` / `canRestore` | `Builder` 且对应 speed>0 | 能力开关 |
| `canResurrect` / `canCapture` | `false` 且对应 speed>0 | 默认关闭 |
| `ShowNanoSpray` | `true` | 是否画纳米粒子 |
| `showNanoFrame` | `true` | 建造中是否画骨架 |
| `nanoColor` | `0.2 0.7 0.2` | 纳米粒子颜色 |
| `BuildOptions` | — | 可建造列表（字符串数组） |

## 5. 移动

| 字段 | 默认 | 说明 |
|---|---|---|
| `speed`（新）/ `MaxVelocity`（旧） | `0` | **单位不同**：`speed` 是 elmo/秒；`MaxVelocity` 是 elmo/帧（×30 = elmo/秒） |
| `maxAcc`（别名 `Acceleration`） | `0.5` | 加速度，elmo/帧²（×900 = elmo/秒²） |
| `maxDec`（别名 `BrakeRate`） | 回落 `maxAcc` | 刹车，同上单位 |
| `TurnRate` | `0` | 转向角速度，单位是 1/65536 圈/帧（900 ≈ 4.9°/帧 ≈ 148°/秒） |
| `TurnInPlace` | `true` | 能否原地转向 |
| `turnInPlaceSpeedLimit` | 自动推算 | 低于此速度才允许原地转（**elmo/帧**） |
| `turnInPlaceAngleLimit` | `0` | 原地转向的角度上限 |
| `MaxSlope` | `0` | **只用来算 `maxHeightDif`**，不控制寻路（寻路看 MoveDef） |
| `maxHeightDif` | `40 × tan(MaxSlope)` | 自动推导，不是可写字段 |
| `FootprintX` / `FootprintZ` | `1` | 占地格数（每格 8 elmo） |
| `MovementClass` | — | 对应 `GameData/MoveDefs.lua` 的 name，移动单位必填 |
| `Upright` | `false` | true = 不跟地形倾斜（引擎的姿态没有倾角上限，见 §10 坑 3） |
| `UpDirSmoothing` | `0`（钳在 0–0.95） | 越大越慢地跟随地形法线 |
| `waterline` | `0` | 相对水面的高度偏移 |
| `floatOnWater`（别名 `floater`） | 有 `WaterLine` 时为 true | 仅对无 MoveDef 的单位有效 |
| `maxWaterDepth` | `+1e7` | 可涉水深度 |
| `minWaterDepth` | `-1e7` | 需要的最小水深 |
| `CanMove` | `false` | 是否可移动（**不写就动不了**） |
| `canFly` | `false` | 是否飞机 |
| `cruiseAltitude` | `0` | 巡航高度 |
| `wingDrag` / `wingAngle` | `0.07` / `0.08` | 飞机气动参数 |
| `pushResistant` | `false` | 抗推挤 |
| `mass` | 回落 `metalCost` | 质量，影响碰撞与冲击 |
| `crushResistance` | 回落 `mass` | 抗碾压 |
| `minCollisionSpeed` | `1.0` | 低于此速度的碰撞不产生伤害 |
| `slideTolerance` | `0` | 斜坡滑移容差 |
| `rollingResistanceCoefficient` | `0.05` | 滚动阻力 |
| `groundFrictionCoefficient` | `0.01` | 地面摩擦 |

## 6. 战斗与能力开关

| 字段 | 默认 | 说明 |
|---|---|---|
| `CanAttack` | `true` | 能否攻击 |
| `canFight` | `true` | 能否自动交战 |
| `CanGuard` | `true` | 能否护卫 |
| `CanPatrol` | `true` | 能否巡逻 |
| `canRepeat` | `true` | 能否循环指令 |
| `CanSelfDestruct` | `true` | 能否自毁 |
| `selfDestructCountdown` | `5` | 自毁倒计时（秒） |
| `kamikaze` | `false` | 撞击自爆 |
| `kamikazeDistance` | `0` | 引爆距离（源码是 `值 + 25`，默认 -25 → 0） |
| `kamikazeUseLOS` | `false` | 需要视线才引爆 |
| `ExplodeAs` | `""` | 死亡特效用的**武器名**（通常是零伤害武器） |
| `SelfDestructAs` | 回落 `ExplodeAs` | 自毁特效 |
| `NoChaseCategory` | `""` | 不追击的分类，如 `AIR` |
| `highTrajectory` | `0` | 高抛弹道（0 平射 / 1 高抛 / 2 仅高抛） |
| `weapons` | — | 武器表，见下 |
| `noAutoFire` | `false` | 禁用开火状态控制 |
| `canDropFlare` / `flareDelay` | `false` / `0.3` | 飞机干扰弹 |

武器子表里还能写：

| 字段 | 默认 | 说明 |
|---|---|---|
| `name` | — | 武器名，逐字匹配 |
| `turret` | 见武器 | 覆盖武器的炮塔属性 |
| `maxAngleDif` | `360` | 射界角度 |
| `badTargetCategory` | `""` | 不打哪些分类 |
| `onlyTargetCategory` | `""`（= 全部） | 只打哪些分类 |
| `mainDir` | 正前方 | 射界中心方向 |
| `slaveTo` | `0` | 跟随另一个武器的瞄准 |
| `weaponAimAdjustPriority` | — | 瞄准优先级 |

## 7. 碰撞体与占地

| 字段 | 默认 | 说明 |
|---|---|---|
| `collisionVolumeType` | `ellipsoid` | `box` / `ellipsoid` / `cylY` / `cylX` / `cylZ` / `sphere` |
| `collisionVolumeScales` | 模型包围盒 | **全长**，不是半径（引擎内部 ×0.5） |
| `collisionVolumeOffsets` | `0 0 0` | 碰撞体中心相对单位原点的偏移 |
| `useFootPrintCollisionVolume` | 未确认 | 直接用 footprint 当碰撞盒 |
| `usePieceCollisionVolumes` | 未确认 | 按模型各部件分别生成 |
| `YardMap` | `""` | 建筑的占位图，字符见源码 `CreateYardMap` |
| `levelGround` | **`true`** | 建筑是否平整地基——**这是 terraform 分支的开关**，见 §10 坑 1 |

> 不写 `collisionVolume*` 时，引擎用的是**模型包围球**（`model->radius`），不是包围盒。坦克那种细长形状会明显偏胖。
>
> `useFootPrintCollisionVolume` / `usePieceCollisionVolumes` 的默认值在 `ParseCollisionVolume` 里，本次没有展开该函数，故标「未确认」。

## 8. 运输与杂项

| 字段 | 默认 | 说明 |
|---|---|---|
| `cantBeTransported` | `!可移动` | 反向键：写了就不能被运 |
| `transportSize` | `0` | 自身作为货物的体积 |
| `transportMass` | `100000` | 自身作为货物的质量 |
| `transportCapacity` | `0` | 作为运输机的容量 |
| `minTransportSize` | `0` | 只接收多大以上的货物 |
| `holdSteady` | `false` | 运输时锁住货物姿态 |
| `Reclaimable` | `true` | 能否被回收 |
| `Repairable` | `true` | 能否被维修 |
| `ActivateWhenBuilt` | `false` | 建好才生效（雷达、护盾常用） |
| `onOffable` | `false` | 能否开关 |
| `isTargetingUpgrade` | `false` | 是否目标共享设施 |

## 9. 本项目现有单位

| 文件 | 定位 |
|---|---|
| `Commander.lua` | 指挥官（DGun + 建造） |
| `Constructor.lua` | 基础建造车 |
| `spider.lua` | 六足工程师（建造者） |
| `Factory.lua` | 工厂（建造者，建移动单位） |
| `Extractor.lua` | 金属提取器 |
| `energyreactor.lua` | 能量反应堆 |
| `LLT.lua` | 轻型激光塔 |
| `mbt.lua` / `m1a1.lua` | 两辆主战坦克 |
| `scout.lua` | 六轮侦察车 |
| `Duron.lua` / `Stumpy.lua` / `Flare.lua` | 沙盒示例单位 |

## 10. 踩过的坑

1. **`terraformSpeed` 默认等于 `WorkerTime`，不是 0。** 但 `levelGround` 默认 `true`，所以建造任何建筑都会先进「平整地基」分支：`CBuilder::Update` 里 `UpdateTerraform` 排在 `UpdateBuild` 前面且用 `||` 短路。`terraformSpeed` 太小 → 地基平不完 → `buildProgress` 长时间为 0（纳米粒子照喷）。给建造者写 `terraformSpeed = 9001` 可以瞬间平完。

2. **`buildTime` 是工作量，不是秒。** 实际耗时 = `buildTime / WorkerTime` 秒。本 mod 里所有单位的 `buildTime` 恰好等于 `metalCost`，于是「每秒金属消耗 = WorkerTime」——`WorkerTime = 6` 就是 6 金属/秒。

3. **`Upright = false` 时引擎会跟地形，但 `GetWantedUpDir` 没有倾角上限**，坡 24° 车体就躺 24°；`UpDirSmoothing` 只能放慢，不能拦住。

4. **`MaxVelocity` 与 `speed` 单位差 30 倍。** 写 `speed = 78` 是 78 elmo/秒；写 `MaxVelocity = 78` 是 2340 elmo/秒。

5. **`CanMove` 默认 false。** 忘了写，单位造出来就是个桩子。

6. **`collisionVolumeScales` 是全长。** 写 `48 33 70` 得到的是 48×33×70 的盒子，不是半径 48。

7. **`MovementClass` 缺失会直接报内容错误**，而且名字必须在 `GameData/MoveDefs.lua` 里存在。

8. **无效键不会报错。** `CanStop` 在引擎二进制里连字符串都不存在（`grep` 结果为 0），确认是空转的键——本项目所有单位都写了 `CanStop = true`，没有任何作用。`lineOfSight` 同理。
