# 宏愿 / 家族集团（House Aspiration / House Bloc）UI 显示代码与 feudal_admin 异常根因分析

> 调查对象：原版 CK3（`D:\SteamLibrary\steamapps\common\Crusader Kings III\game`）
> 模组：`大梦春秋 III`（workshop `3598369228`）
> 触发背景：模组在 `common/governments/02_government_types_COPF.txt` 的 `feudal_admin_government` 上新增
> `government_has_house_blocs`（flags 块）并将 `house_aspirations = no` 改为 `yes`，
> 用户启用后报告「宏愿 UI 有异常」。
> 结论先行：**异常不是 GUI 渲染 bug，而是数据/脚本门控缺口——两处 flag 改动是必要但不充分的条件。**
> **不需要改 GUI**，修复点在 `common/house_aspirations/`（放宽 6 个集团宏愿的 `is_shown`）。

---

## 一、结论速览（TL;DR）

| 项 | 内容 |
|----|------|
| 宏愿选择器文件 | `gui/window_house_aspiration.gui` |
| 家族集团 / 游牧联盟共用窗口 | `gui/window_confederation.gui`（按 `ConfederationType.IsHouseBasedConfederation` 切换，数据驱动，**与政府形态无关**） |
| 入口 | `gui/window_dynasty_house.gui:3020` `ToggleGameViewData('house_aspiration_window', DynastyHouse.Self)`，可见性由 `DynastyHouse.UsesHouseAspirations` 门控（`:547`/`:588`） |
| 集团信息条 / 打开集团窗口 | `gui/window_dynasty_house.gui:585` + `:909-939`，可见性 `[Confederation.IsValid]` |
| 真正根因 | 驱动家族集团的 **6 个宏愿（ceremony/determination/humility/prosperity/service/strength）被 `government_is_japanese_trigger` 排除**，feudal_admin 一个都选不到；选择器于是只给「行政家族权势（Family Power）」宏愿（13 个，**无 `confederation_type` 映射**）。选了也永远生成不了 `house_bloc_*` 联盟，集团窗口永不出现。 |
| GUI 是否需要改 | **否。** 所有相关 GUI 都是数据驱动，`government_has_house_blocs` 已能让交互与窗口工作。 |
| 需要改什么 | 在 `common/house_aspirations/` 覆盖 6 个集团宏愿的 `is_shown`，加入 `government_has_flag = government_has_house_blocs` 分支（见第五节）。 |

---

## 二、UI 文件定位

### 2.1 宏愿选择器 `gui/window_house_aspiration.gui`（1075 行）
宏愿（House Aspiration）的**选择/编辑窗口**，由 dynasty house 面板点击进入。

关键结构：
- 根 `window`（`:5-63`）`datacontext = "[HouseAspirationWindow.GetDynastyHouse]"`，打开即 `house_aspiration_window` 视图。
- 两种布局，靠 C++ 函数 `HasSpecialHouseAspiration(DynastyHouse)` 二选一（`:56-61`）：
  ```ini
  vbox_house_aspirations_custom   = { visible = "[HasSpecialHouseAspiration(DynastyHouse)]" }   # 日本家族属性（特殊）模式
  hbox_house_aspirations_default  = { visible = "[Not(HasSpecialHouseAspiration(DynastyHouse))]" } # 通用/行政模式
  ```
- 可选项列表来自 C++ 数据模型（`:176`、`:190`、`:385`）：
  ```ini
  datamodel = "[HouseAspirationWindow.GetAvailableHouseAspirations]"
  ```
  **列表内容完全由数据（各 `house_aspiration` 定义的 `is_shown`）决定**，GUI 不硬编码任何政府形态。
- 选择/确认：`HouseAspirationWindow.SelectHouseAspiration` / `ConfirmHouseAspiration` / `UpgradeHouseAspiration`（纯 C++ 命令，无政府判断）。

### 2.2 家族集团 / 游牧联盟共用窗口 `gui/window_confederation.gui`（1075 行）
联盟/集团展示窗口。两套布局互斥显示，由 `ConfederationType.IsHouseBasedConfederation` 切换（**来自 `confederation_type` 的 `house_based_confederation` 标志，不是政府形态**）：

| 行号 | 元素 | 可见性 |
|------|------|--------|
| `:40` | 家族集团背景图 `tgp_japanese_shogunate.dds` | `[ConfederationType.IsHouseBasedConfederation]` |
| `:58` | 游牧背景图 `mpo_decision_confederation.dds` | `[Not(ConfederationType.IsHouseBasedConfederation)]` |
| `:80` | 凝聚力复杂进度条 `bloc_cohesion_complex_bar` | `[ConfederationType.IsHouseBasedConfederation]` |
| `:98` | 成员家族网格 `bloc_confederation_holder` | `[ConfederationType.IsHouseBasedConfederation]` |
| `:121` | 成员角色列表 `nomadic_confederation_holder` | `[Not(ConfederationType.IsHouseBasedConfederation)]` |
| `:143` | 领导家族条 `hbox_confederation_bloc_leader` | `[And(ConfederationType.IsHouseBasedConfederation, Confederation.HasLeadingHouse)]` |

→ **只要存在一个 `house_bloc_*` 类型的联盟，该窗口对 feudal_admin 也能正确渲染**，无需任何硬编码政府判断。

### 2.3 入口与集团信息条 `gui/window_dynasty_house.gui`
- 入口按钮（打开宏愿选择器）：`:3020`
  ```ini
  onclick = "[ToggleGameViewData( 'house_aspiration_window', DynastyHouse.Self )]"
  ```
- 宏愿区可见性（`:547`、`:588`）：
  ```ini
  visible = "[Or( DynastyHouse.UsesHouseAspirations, Character.HasDomicile )]"   # :547 整个区
  visible = "[DynastyHouse.UsesHouseAspirations]"                               # :588 宏愿等级显示
  ```
  `DynastyHouse.UsesHouseAspirations` 是 C++ 函数，实质由政府的 `house_aspirations` 规则决定——feudal_admin 现设为 `yes`，故 **UI 入口已出现**（这正是用户「能看到宏愿 UI」的原因）。
- 家族集团信息条（`:585` 引用 `hbox_house_bloc_info`，定义 `:909-939`）：
  ```ini
  type hbox_house_bloc_info = hbox {
      datacontext = "[DynastyHouse.GetConfederation]"
      visible = "[Confederation.IsValid]"                       # :911 只有已存在联盟才显示
      ...
      coa_bloc_tiny = { onclick = "[OpenGameViewData( 'confederation_window', Confederation.Self )]" }  # :927 打开集团窗口
  }
  ```
  → 集团信息条与集团窗口都**依赖「已存在一个联盟」**；联盟不生成，则这条永远隐藏。

---

## 三、可见性门控（精确 trigger 与硬编码检查）

### 3.1 入口门控（已满足）
- `DynastyHouse.UsesHouseAspirations` ← 政府 `house_aspirations = yes` → feudal_admin 已满足（`:62`）。
- `tgp_uses_house_blocs_trigger`（`common/scripted_triggers/10_tgp_house_bloc_triggers.txt:2-6`）：
  ```ini
  tgp_uses_house_blocs_trigger = {
      has_tgp_dlc_trigger = yes
      government_has_flag = government_has_house_blocs     # feudal_admin 已加此 flag
      top_liege = { government_has_flag = government_has_house_blocs }
  }
  ```
  → feudal_admin（及其 top_liege）满足，家族集团交互（`join_house_bloc_interaction` 等）可用。

### 3.2 宏愿可用性的真正硬门控（根因所在）
宏愿是否出现在 `GetAvailableHouseAspirations`，由各 `house_aspiration` 定义的 **`is_shown`** 决定。

**(a) 驱动家族集团的 6 个宏愿** —— `common/house_aspirations/10_tgp_japan_house_aspirations.txt`：
```ini
ceremony = {                                       # :30
    show_in_main_hud = yes
    is_shown = {
        house_head ?= { government_is_japanese_trigger = yes }   # :33  ← 关键硬门控
    }
    confederation_type = house_bloc_ceremony        # :37  ← 与集团类型挂钩
    level = {
        ...
        parameters = {
            ceremony_cheaper_feasts = yes           # :54  ← 集团创建时用于识别
            aspiration_ceremony = yes                # :55
        }
    }
}
```
`determination / humility / prosperity / service / strength` 五个结构完全一致，均 `is_shown = { government_is_japanese_trigger = yes }`，且各自带 `confederation_type = house_bloc_*`。

`government_is_japanese_trigger` 的定义（`common/scripted_triggers/10_tgp_japan_triggers.txt:366-371`）：
```ini
government_is_japanese_trigger = {
    OR = {
        government_has_flag = government_is_japan_administrative
        government_has_flag = government_is_japan_feudal
    }
}
```
→ **feudal_admin 的 flags 是 `government_is_feudal_admin` / `government_is_feudal`，并不含 `government_is_japan_*`**，因此这 6 个宏愿对 feudal_admin **`is_shown` 全为 false**，不会进入选择器。

**(b) 行政「家族权势（Family Power）」宏愿** —— `common/house_aspirations/00_admin_house_powers.txt`（13 个：diplomatic_envoys / staunch_stewards / learned_philosophers / tax_assessors / army_commanders / army_quartermasters / tactical_besiegers / political_meddlers / confident_schemers / charismatic_socialites / respected_despots / lofty_architects / faithful_nobles）：
```ini
diplomatic_envoys = {                               # :15
    is_shown = {
        house_head ?= {
            government_allows = administrative      # feudal_admin 有 administrative = yes 规则 ✓
            government_has_flag = government_has_powerful_families   # feudal_admin flags 含此项 ✓
            NOR = {
                government_has_flag = government_uses_merit_family_aspirations
                government_is_japanese_trigger = yes               # feudal_admin 为 NO → NOR 通过 ✓
            }
        }
    }
    # 注意：这些宏愿没有 confederation_type 字段
}
```
→ feudal_admin 满足上述条件，**这 13 个行政家族权势宏愿全部 `is_shown = true`**。它们消耗 influence、分 3 级，**但没有任何 `confederation_type` 映射**。

### 3.3 集团创建门控（已满足，但前提是「家以获得 6 宏愿之一」）
- 交互 `join_house_bloc_interaction` 的 `is_available`（`common/character_interactions/10_tgp_japan_interactions.txt:53-89`）：
  ```ini
  is_available = {
      government_has_flag = government_has_house_blocs        # :54 ✓ feudal_admin 已加
      house.house_head ?= this                                # 须为家族族长
      tgp_house_bloc_interaction_valid_trigger = yes          # :56
      ...
  }
  ```
  `tgp_house_bloc_interaction_valid_trigger`（`:619-624`）：
  ```ini
  tgp_house_bloc_interaction_valid_trigger = {
      is_ruler = yes
      tgp_uses_house_blocs_trigger = yes
      highest_held_title_tier >= tier_county
      top_liege = { tgp_uses_house_blocs_trigger = yes }
  }
  ```
  → **不含 `government_is_japanese_trigger`**，feudal_admin 满足。
- 集团实际创建在交互成功、家族尚无联盟时调用（`10_tgp_japan_interactions.txt:369`、`:893`）：
  ```ini
  tgp_create_house_bloc_effect = { TYPE = none }
  ```
  其逻辑（`common/scripted_effects/10_dlc_tgp_house_bloc_scripted_effects.txt:11-115`）用 `has_house_aspiration_parameter` 识别类型：
  ```ini
  else_if = { limit = { OR = { has_house_aspiration_parameter = unlocks_japanese_manor_watch_house
                               scope:type = flag:determination } }
      house_head = { create_confederation = { type = confederation_type:house_bloc_determination ... } } }
  # 同理 ceremony_cheaper_feasts→house_bloc_ceremony, unlocks_japanese_manor_shrine→humility,
  #        unlocks_japanese_manor_brewery→prosperity, ..._archive→service, ..._armory→strength
  ```
  → **若家族没有任何 6 宏愿参数（ceremony_cheaper_feasts 等），`tgp_create_house_bloc_effect` 六个分支全不匹配 → 不调用 `create_confederation` → 联盟永不生成。**

---

## 四、显示内容的分支逻辑

1. **选择器模式分支（custom vs default）**
   `window_house_aspiration.gui:56-61` 用 `HasSpecialHouseAspiration(DynastyHouse)` 切换。
   - feudal_admin 无 `has_special_house_aspirations` 标志 → 走 **default** 模式（`hbox_house_aspirations_default`），以列表渲染 `GetAvailableHouseAspirations`，每个项 `button_standard` + `HouseAspiration.GetName/GetSmallIcon`。
   - 该模式对「任意被 `is_shown` 放行的宏愿」都通用，本身无政府硬编码。

2. **列表项来源**
   `GetAvailableHouseAspirations`（C++）遍历 `common/house_aspirations/` 全部定义，按各自 `is_shown` 过滤。
   - feudal_admin 当前：`13` 个行政家族权势宏愿 ✅ + `6` 个集团宏愿 ❌ = 仅 13 个可见。

3. **集团窗口内容分支（家族集团 vs 游牧）**
   `window_confederation.gui` 全部用 `ConfederationType.IsHouseBasedConfederation`（来自联盟类型数据 `house_based_confederation`），**不读政府形态**。因此一旦 `house_bloc_*` 联盟存在，feudal_admin 的窗口与游牧/日本完全一致。

4. **宏愿类型如何从数据列出**
   每个 `house_aspiration` 定义的 `level` 块提供 `GetLevels`；`parameters` 块提供 `has_house_aspiration_parameter` 判定；带 `confederation_type` 的才与集团类型绑定。

---

## 五、feudal_admin 异常根因假设

### 改动实际达成的效果
| 改动 | 结果 |
|------|------|
| `flags += government_has_house_blocs` | ✅ `tgp_uses_house_blocs_trigger` 通过；家族集团交互、集团窗口基础设施可用 |
| `house_aspirations = yes` | ✅ `DynastyHouse.UsesHouseAspirations` 通过；dynasty house 面板出现宏愿区，可打开选择器 |

### 关键缺口（根因）
**驱动家族集团的 6 个宏愿被 `government_is_japanese_trigger` 排除**，而 feudal_admin 不是日本政体。于是：
- 选择器只提供 **13 个行政家族权势宏愿**（影响/分 3 级，**无 `confederation_type`**）；
- 玩家无论选哪个，家族都拿不到 `ceremony_cheaper_feasts` 等参数；
- `tgp_create_house_bloc_effect` 六个分支全部落空 → **永不生成 `house_bloc_*` 联盟**；
- `hbox_house_bloc_info`（`[Confederation.IsValid]`）与集团窗口永远不出现。

### 用户感知到的「异常」两种可能表现
1. **看到的是「行政家族权势」界面（influence 消耗、3 级、与集团无关）**，而非预期的 6 选 1 集团宏愿界面——即「宏愿 UI 内容不对」。
2. 或者界面看似可用、能选能确认，但**选完没有任何集团产生**，看似「功能残缺/卡死」。

两种表现同源：**选择器提供的选项集合错误（缺 6 集团宏愿、多 13 家族权势宏愿）**，而非 GUI 渲染错误。

> 注意：`HasSpecialHouseAspiration` 走 default 模式，所以并不会因为「缺 `has_special_house_aspirations`」而报错——它只是不显示日本特殊家族属性布局。真正阻断功能的是 6 宏愿的 `is_shown`。

---

## 六、修复建议

### 6.1 结论：**不需要任何 GUI 改动。**
`window_house_aspiration.gui`、`window_confederation.gui`、`window_dynasty_house.gui` 均已数据驱动，feudal_admin 只要能获得 6 个集团宏愿之一，整条链路（选择器 → 确认 → 交互 → 创建联盟 → 集团窗口）即可工作。**GUI override 只会引入维护风险，无收益。**

### 6.2 需要的数据/脚本修复：放宽 6 个集团宏愿的 `is_shown`
在模组新增（或扩展）`common/house_aspirations/zz_copf_house_bloc_aspirations.txt`，**完整重定义**这 6 个 key（CK3 同名 key 后加载覆盖整体），把 `is_shown` 从「仅日本」放宽为「日本 **或** 带 `government_has_house_blocs` 的政府」。示例（`ceremony`）：

```ini
# zz_copf_house_bloc_aspirations.txt  （加载顺序须在 10_tgp_japan_house_aspirations.txt 之后）
ceremony = {
    show_in_main_hud = yes
    is_shown = {
        house_head ?= {
            OR = {
                government_is_japanese_trigger = yes
                government_has_flag = government_has_house_blocs   # ← 让 feudal_admin 也能选
            }
        }
    }
    confederation_type = house_bloc_ceremony
    level = {
        cost = { prestige = house_aspiration_level_1_cost_value }
        powerful_family_member_modifier = { negate_diplomacy_penalty_add = 1 }
        any_house_member_modifier = { diplomacy = 1 monthly_prestige_gain_mult = 0.05 }
        parameters = { ceremony_cheaper_feasts = yes aspiration_ceremony = yes }
        ai_score = { value = 1 ... }
    }
    # level 2 / level 3 照抄原版 10_tgp_japan_house_aspirations.txt 中对应块
    cooldown = { years = 5 }
    illustration = "gfx/interface/icons/culture_pillars/ethos_communal.dds"
}
```
对 `determination / humility / prosperity / service / strength` 做**同样的 `is_shown` 放宽**（各自保留原版 `confederation_type = house_bloc_*` 与 `parameters`）。

为什么够用（端到端验证）：
- `is_shown` 放宽后，`GetAvailableHouseAspirations` 对 feudal_admin 包含 6 集团宏愿；
- 玩家选 `ceremony` → 家族获得 `ceremony_cheaper_feasts` 参数 + `confederation_type = house_bloc_ceremony`；
- `join_house_bloc_interaction` 的 `is_available` 已满足（feudal_admin 有 `government_has_house_blocs` 且 `tgp_house_bloc_interaction_valid_trigger` 无日本政体要求）；
- 交互成功 → `tgp_create_house_bloc_effect` 命中 `ceremony_cheaper_feasts` 分支 → 创建 `house_bloc_ceremony`；
- `DynastyHouse.GetConfederation` 变为有效 → `hbox_house_bloc_info` 出现 → 点开 `confederation_window`（数据驱动，正确渲染）。

### 6.3 次要打磨（可选，非必须）
- **选择器 clutter**：放宽后选择器会同时出现 13 个行政家族权势宏愿 + 6 个集团宏愿。若模组只想要集团宏愿，可给 13 个行政宏愿的 `is_shown` 加 `NOR { government_has_flag = government_has_house_blocs }` 排除（或在模组里整体覆盖 `00_admin_house_powers.txt` 加 `government_is_feudal_admin` 排除）。
- **realm 数量限制**：`join_house_bloc_interaction` 的 `is_available` 含「同 realm 已有 ≥5 个联盟则不可」（`:70-74`）、「同 aspiration 的联盟已存在则不可」（`:80-86`）。大型 total conversion 可能想放宽，按需覆盖。
- **`has_special_house_aspirations`**：不要给 feudal_admin 加此 flag 来「走 custom 模式」——它会连带启用日本特殊家族属性 UI 与其他日本专属内容，blast radius 过大。保持 default 模式即可。

### 6.4 验证步骤
1. 启动带 TGP 的存档，用 feudal_admin 角色打开 dynasty house 面板 → 宏愿区可见 → 打开宏愿选择器。
2. 确认选择器中出现 ceremony/determination/humility/prosperity/service/strength 六个选项。
3. 选其一（如 ceremony）→ 确认无报错；用 `join_house_bloc_interaction`（或对应创建交互）对同 realm 家族发起。
4. 成功后 dynasty house 面板出现集团信息条 → 点开 `confederation_window` → 应显示凝聚力条、成员家族网格、领导家族条（即 `IsHouseBasedConfederation` 布局）。
5. 若用调试指令 `set_house_aspiration = { type = ceremony }` 后检查 `has_house_aspiration_parameter = ceremony_cheaper_feasts` 为真。

---

## 七、关键文件 / 行号速查表

| 主题 | 文件 | 行号 | 片段 |
|------|------|------|------|
| 宏愿选择器窗口 | `gui/window_house_aspiration.gui` | 56-61 | `HasSpecialHouseAspiration` 切换 custom/default |
| 选择器列表来源 | `gui/window_house_aspiration.gui` | 176/190/385 | `GetAvailableHouseAspirations` |
| 集团/游牧共用窗口 | `gui/window_confederation.gui` | 40/80/98/121/143 | `IsHouseBasedConfederation` 分支 |
| 宏愿入口 | `gui/window_dynasty_house.gui` | 3020 | `ToggleGameViewData('house_aspiration_window',...)` |
| 宏愿区可见性 | `gui/window_dynasty_house.gui` | 547/588 | `DynastyHouse.UsesHouseAspirations` |
| 集团信息条 | `gui/window_dynasty_house.gui` | 585/909-939 | `[Confederation.IsValid]` / `OpenGameViewData('confederation_window',...)` |
| 集团交互可用性 | `common/character_interactions/10_tgp_japan_interactions.txt` | 53-89, 369, 893 | `government_has_house_blocs` + `tgp_create_house_bloc_effect` |
| 6 集团宏愿定义 | `common/house_aspirations/10_tgp_japan_house_aspirations.txt` | 30-… | `is_shown = government_is_japanese_trigger`；`confederation_type` |
| 13 行政家族权势宏愿 | `common/house_aspirations/00_admin_house_powers.txt` | 15-… | `government_allows = administrative` 等；无 `confederation_type` |
| 日本政体判定 | `common/scripted_triggers/10_tgp_japan_triggers.txt` | 366-371 | `government_is_japanese_trigger` |
| 集团交互有效性 | `common/scripted_triggers/10_tgp_japan_triggers.txt` | 619-624 | `tgp_house_bloc_interaction_valid_trigger`（无日本要求） |
| 集团创建映射 | `common/scripted_effects/10_dlc_tgp_house_bloc_scripted_effects.txt` | 11-115 | `has_house_aspiration_parameter` → `house_bloc_*` |
| 集团 DLC/flag 门控 | `common/scripted_triggers/10_tgp_house_bloc_triggers.txt` | 2-6 | `tgp_uses_house_blocs_trigger` |
| 模组改动点 | `common/governments/02_government_types_COPF.txt` | 62, 102 | `house_aspirations = yes`；`government_has_house_blocs` |

---

*附：本分析基于原版 `game` 目录静态阅读，未运行游戏。`HasSpecialHouseAspiration` / `DynastyHouse.UsesHouseAspirations` / `GetAvailableHouseAspirations` 为 C++ 作用域函数，其行为按原版数据（government 规则、`is_shown`）推断，与原版实际表现一致。*
