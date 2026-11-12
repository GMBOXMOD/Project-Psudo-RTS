# WeaponDef 字段速查

> 依据：Recoil 引擎 `rts/Sim/Weapons/WeaponDef.cpp` 的 `WEAPONTAG` 声明（2026-11 拉取的 master）。
> 「默认」列就是源码里的 `defaultValue`，不填时引擎用的值。
> 键名经 `lowerkeys()` 处理，**大小写不敏感**；但 `name` 里的武器名字符串是大小写敏感的。
>
> 单位字段见 [UNITDEF_API.md](UNITDEF_API.md)。

## 0. 文件骨架

```lua
-- Weapons/MyGun.lua
local weaponName = "MyGun"           -- 单位里按这个名字引用，逐字匹配

local weaponDef = {
    name       = "My Gun",           -- 界面上显示的名字
    weaponType = "Cannon",
    range      = 600,
    reloadTime = 2.0,
    damage     = { default = 200 },
}

return lowerkeys({ [weaponName] = weaponDef })
```

单位侧：

```lua
weapons = {
    [1] = { name = "MyGun" },                    -- 炮塔武器
    -- [2] = { name = "ScoutGun", turret = false },  -- 跟车体转的副武器
}
```

---

## 1. 身份与基础

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | string | `"Weapon"` | 界面显示名 |
| `weaponType` | string | `"Cannon"` | 决定弹道模型与一堆默认值，见 §7 |
| `range` | float | `10` | 索敌射程（elmo）。弹道武器实际落点可能更近 |
| `reloadTime` | float | `1.0` | 两轮之间秒数。**从第一发开始计时**，不是最后一发 |
| `turret` | bool | `false` | true = 有独立射界；false = 必须整车对准 |
| `tolerance` | float | `3000` | 仅 `turret=false` 有效：开火锥角（16 位角度单位） |
| `firetolerance` | float | `3640` | 瞄准容差（TA 角度单位，内部转 cos） |
| `windup` | float | `0` | 开火前摇（秒） |
| `rechargeDelay` | float | `0` | 两轮之间的额外冷却（秒） |
| `heightMod` | float | `0.2` | 高度差对索敌的影响权重，0 = 忽略高度 |

## 2. 弹道与物理

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `weaponVelocity` | float | `0`（最小 0.01） | 弹速，elmo/秒 |
| `startVelocity` | float | `0` | 导弹初速（会加速到 `weaponVelocity`） |
| `weaponAcceleration` | float | `0` | 导弹加速度，elmo/秒² |
| `flightTime` | float | `0` | 导弹燃料时间（秒），到点自爆 |
| `myGravity` | float | `0` | 只作用于这发弹的额外重力，0 = 直线 |
| `gravityAffected` | bool | `false` | 主要给 `DGun` 用，抛物弹 |
| `groundBounce` | bool | `false` | 落地反弹 |
| `bounceRebound` | float | `1.0` | 反弹保留的速度比例 |
| `bounceExplosionGenerator` | string | `""` | 反弹时的特效 |
| `dance` | float | `0` | 导弹左右摆动幅度 |
| `wobble` | float | `0` | 导弹抖动幅度 |
| `tracks` | bool | `false` | 导弹持续转向追踪 |
| `turnRate` | float | `0` | 追踪转向速率（16 位角度/帧） |
| `fixedLauncher` | bool | `false` | 导弹沿发射管方向飞出，不直接朝目标 |
| `collisionSize` | float | 见 §7 | 弹体碰撞半径（`Flame`/`LaserCannon` 0.5，`DGun` 10） |

## 3. 伤害

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `damage` | table | `{default=1}` | 按装甲分类给值，见 §8 |
| `areaOfEffect` | float | `8` | **直径**，不是半径。引擎内部 ×0.5 变半径 |
| `impulseFactor` | float | `1` | 冲击力倍数。通常基础冲击 = 伤害值 |
| `craterMult` | float | `1`（回落 `impulseFactor`） | 弹坑大小倍数，0 = 不挖地 |
| `craterBoost` | float | `0` | 弹坑额外加成 |
| `paralyzer` | bool | `false` | 只瘫痪不伤害 |
| `energyPerShot` | float | `0` | 每发耗电 |
| `metalPerShot` | float | `0` | 每发耗金属 |

## 4. 命中与精度

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `accuracy` | float | `0` | 整轮的散布角，越大越不准，0 = 完美 |
| `sprayAngle` | float | `0` | 单发之间的散布角（配合 `projectiles`） |
| `movingAccuracy` | float | 回落 `accuracy` | 移动时的散布 |
| `targetMoveError` | float | `0` | 对移动目标的提前量误差比例 |
| `leadLimit` | float | `-1` | 提前量上限（elmo），负数 = 不限 |
| `predictBoost` | float | `0.5` | 仅自爆类武器，命中预测权重 |
| `sweepfire` | bool | `false` | 光束武器换目标时持续开火「扫」过去 |
| `burnblow` | bool | `false`（`LaserCannon` 为 `true`） | 到射程末端自爆 |

## 5. 目标与碰撞

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `commandFire`（别名 `manualfire`） | bool | `false` | 只能手动点（DGun 那种） |
| `avoidFriendly` | bool | `true` | 友军挡路就不开火 |
| `avoidFeature` | bool | `true` | 障碍物挡路就不开火 |
| `avoidGround` | bool | `true` | 地形挡路就不开火 |
| `avoidNeutral` | bool | `false` | 中立单位挡路是否避让 |
| `avoidCloaked` | bool | `false` | 隐身单位挡路是否避让 |
| `collideEnemy` | bool | `true` | 撞敌人会爆 |
| `collideFriendly` | bool | `true` | 撞友军会爆 |
| `collideFeature` | bool | `true` | 撞障碍物会爆 |
| `collideNeutral` | bool | `true` | 撞中立会爆 |
| `collideGround` | bool | `true` | 撞地会爆 |
| `collideCloaked` | bool | `true` | 撞隐身单位会爆 |
| `collideFireBase` | bool | `false` | 撞到自己发射点会爆 |
| `collideNonTarget` | bool | `true` | 撞非目标单位会爆 |
| `targetable` | int | `0` | 能被哪些武器拦截（位掩码） |
| `interceptor` | int | `0` | 能拦截哪些武器（位掩码） |
| `stockpile` | bool | `false` | 需要预先生产弹药 |
| `burst`（别名 `salvosize`） | int | `1` | 一轮几发 |
| `burstRate`（别名 `salvodelay`） | float | `0.1` | 轮内间隔（秒） |
| `projectiles` | int | `1` | 每次发射几颗弹丸 |
| `waterweapon` | bool | `false` | 弹道可入水（`TorpedoLauncher` 默认 true） |
| `submissile` | bool | `false` | 鱼雷可出水当导弹用 |

## 6. 表现与声音

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `rgbColor` | float3 | `1 0.5 0` | 弹丸/光束颜色，写 `"1 0.85 0.4"` |
| `size` | float | `2 + min(damage×0.0025, areaOfEffect×0.1)` | 弹丸大小（`EmgCannon` 默认 3） |
| `stages` | int | `5` | 拖尾段数，越多越顺滑也越费 |
| `separation` | float | `1` | 拖尾段间距 |
| `scrollSpeed` | float | `5` | 拖尾纹理滚动速度 |
| `smokeTrail` | bool | `false` | 烟雾拖尾 |
| `smokePeriod` | int | `1` | 每几帧冒一次烟 |
| `smokeSize` | float | `7` | 烟团大小 |
| `model` | string | `""` | 导弹实体模型，如 `"Rocket.s3o"` |
| `cegTag` | string | `""` | 飞行拖尾 CEG，如 `"Rocket_trail"` |
| `explosionGenerator` | string | `""` | 命中特效，写 `"custom:xxx"`，见 `GameData/Explosions/` |
| `thickness` | float | `2.0` | 光束粗细 |
| `coreThickness` | float | `0.25` | 光束核心粗细比例 |
| `laserFlareSize` | float | `15` | 光束端点光斑大小 |
| `duration` | float | `0.05` | 光束存活时间（`LaserCannon`） |
| `largeBeamLaser` | bool | `false` | 大光束（配 `BeamLaser` 用） |
| `beamDecay` | float | `1.0` | 光束衰减 |
| `hardStop` | bool | `false` | 光束到目标即停 |
| `textures.1`~`.4`（别名 `texture1`~`4`） | string | `""` | 光束/拖尾贴图，如 `"largelaser"`、`"flare"` |
| `soundStart` / `soundStartVolume` | string / float | `""` / `1.0` | 开火音效 |
| `soundHitDry` / `soundHitWet` | string | `""` | 命中音效（陆地 / 水面），会回落到 `soundHit` |
| `soundTrigger` | bool | 单发武器为 true | 声音由发射触发还是由命中触发 |

---

## 7. weaponType 速查

| 类型 | 弹道模型 | 会被覆盖的默认值 |
|---|---|---|
| `Cannon` | 抛物弹丸（等离子球视觉） | `heightMod=0.8`，`intensity=0.2` |
| `LaserCannon` | 直线弹丸（慢速激光视觉） | `burnblow=true`，`collisionSize=0.5` |
| `BeamLaser` | 瞬时命中，光束 | `heightMod=1.0` |
| `LightningCannon` | 瞬时命中，闪电 | `heightMod=1.0` |
| `MissileLauncher` | 可追踪，带烟尾 | — |
| `TorpedoLauncher` | 鱼雷，默认不能出水 | `waterweapon=true` |
| `StarburstLauncher` | 先垂直爬升的导弹 | — |
| `AircraftBomb` | 轰炸机投弹（内部转 Torpedo/Cannon） | — |
| `Flame` | 非弹道，火焰精灵 | `duration=flameGfxTime`（默认 1.2），`collisionSize=0.5` |
| `Melee` | 直接结算伤害 | `targetBorder=1.0`，`cylinderTargeting=1.0` |
| `DGun` | 火球，硬编码视觉 | `collisionSize=10`，`leadLimit=0` |
| `EmgCannon` / `Rifle` | 废弃类型，别用 | `size=3.0` |

`weaponType` 决定**哪些字段有意义**：给 `LaserCannon` 设 `weaponVelocity` 基本无效，给 `Cannon` 设 `thickness` 也不会显示。

## 8. damage 分类键

`damage` 是按单位 `Category` 字符串索引的表：

```lua
damage = {
    default = 200,   -- 没匹配到任何分类时用这个
    AIR     = 400,   -- 单位 Category 含 "AIR" 时翻倍
    SUB     = 0,     -- 对潜艇无效
    BUILDING= 150,
}
```

可用的键就是你写在单位 `Category` 里的词（`LAND`、`AIR`、`TANK`、`BUILDING`、`NOTAIR` 等）。匹配是**取最高优先级的那一个**，不会叠加。不写 `default` 时默认伤害是 1。

## 9. 本项目现有武器

| 武器名 | 类型 | 射程 | 伤害 | 装填 | 用在 |
|---|---|---|---|---|---|
| `CommanderLaserBlaster` | LaserCannon | 350 | 125 | 0.75 | Commander |
| `CommanderDgun` | DGun | 325 | 99999 | 2.0 | Commander（D 键） |
| `StumpyLaserBlaster` | LaserCannon | 235 | 11.3 | 0.26 | Stumpy |
| `DuronPlasmaGun` | Cannon | 360 | 102 | 2.75 | Duron |
| `FlareMissle` | MissileLauncher | 700 | 36（对空 72） | 2.8 | Flare |
| `LLTLaserBlaster` | LaserCannon | 550 | 86 | 0.78 | LLT |
| `MBTGun` | Cannon | 620 | 350 | 3.2 | mbt |
| `M1A1Gun` | Cannon | 620 | 350 | 3.2 | m1a1 |
| `ScoutGun` | Cannon | 430 | 65 | 0.9 | scout |
| `M1A1Death` | Cannon | — | 0 | — | 死亡特效专用 |

## 10. 踩过的坑

1. **`areaOfEffect` 是直径。** 写 `64` 实际是 32 elmo 半径。想覆盖一个坦克长度（约 70 elmo）得写 140。
2. **`reloadTime` 从第一发开始计时**，所以 `burst=3, burstRate=0.1, reloadTime=0.5` 会变成连续射击——因为轮内还没打完冷却就到了。
3. **键名不区分大小写，武器名区分。** `M1A1Gun` 写成 `M1A1gun` 会报 `Couldn't find WeaponDef`，单位照样造出来，只是没武器。
4. **未知 tag 会被静默忽略**（引擎只做 `ReportUnknownTags`，不一定进日志）。本项目 `LLTBlaster.lua` 里的 `renderType`、`beamlaser` 在源码里**不存在**，写了没效果——要调光束外观用 `largeBeamLaser` / `thickness` / `textures.1~4`。
5. **`tolerance` 只对 `turret=false` 生效**；有炮塔的武器靠 `firetolerance`。
6. **零伤害武器可以只当特效载体。** `M1A1Death` 就是 `damage.default = 0`，单位用 `ExplodeAs = "M1A1Death"` 借它的 `explosionGenerator`。
7. **`custom:` 前缀**指向 `GameData/Explosions/` 里的 CEG 定义，写成 `duronflash` 会找不到。

---

## 11. 曲射炮（自行火炮）调参

弧线由三个量决定：`range`、`weaponVelocity`、重力 `g`。引擎会解抛物线，选**低弹道**解（除非开 `highTrajectory`）。

```
sin(2θ) = range × g / v²        45° 时射程最大 = v² / g
顶点     = v² × sin²θ / (2g)
```

`g` 的来源：本 mod 地图是 **100**（`mapinfo.lua` 的 `gravity`），引擎默认是 130。

### 低弹道 vs 高抛（g=100，range=340）

| 初速 | 低弹道 | 高弹道 |
|---|---|---|
| 215 | 23.7°，顶点 37 | 66.3°，顶点 194 |
| 245 | 17.3°，顶点 26 | 72.7°，顶点 274 |
| 1000 | 1.0°，顶点 1 | 89°，顶点 **4999** ← 这就是"像导弹" |

结论：**高抛开关没错，错的是配了高初速**。想要臼炮弧线，必须 `highTrajectory = 1` **且** 初速压到 250 上下。

### 三个开关

| 字段 | 说明 |
|---|---|
| `highTrajectory = 0` | 低弹道（默认），打不远才抬高 |
| `highTrajectory = 1` | 高弹道优先，可被玩家 `/trajectory` 切换 |
| `highTrajectory = 2` | 只能高抛 |
| `myGravity` | **单位是每帧²**，`0.1333` = 120 elmo/s²；写 `0` 才用地图重力 |
| `range` | 只决定"打不打"，不决定"打不打得到" |

`myGravity != 0` 时引擎**完全忽略地图重力**（`mix(map.gravity, -myGravity, myGravity != 0)`）。ZK 就是这么做的：`gamedata/weapondefs_post.lua` 给所有 `Cannon` 强制 `myGravity = 120 / 30² = 0.1333`，注释写着 "maps cannot be trusted"。好处是换地图手感不变。

### 调参顺序

1. 定 `range`（目标交战距离）
2. 按想要的仰角反推初速：`v = sqrt(range × g / sin(2θ))`；要 45° 就 `v = sqrt(range × g)`
3. 需要固定手感就写 `myGravity = g / 900`，别让地图重力影响
4. 最后才调 `areaOfEffect`（直径）和 `impulseFactor`

