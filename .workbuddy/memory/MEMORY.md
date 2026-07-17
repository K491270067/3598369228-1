# 大梦春秋 III（CK3 模组）项目笔记

- 性质：CK3 1.19.0.6 中式 total conversion 模组，工作目录 `D:\SteamLibrary\steamapps\workshop\content\1158310\3598369228`，mod 名「大梦春秋 III」。
- 关键路径：原版 `D:\SteamLibrary\steamapps\common\Crusader Kings III\game`；日志 `E:\documents\Paradox Interactive\Crusader Kings III\logs\{error.log(20MB),game.log}`；崩溃 `E:\documents\Paradox Interactive\Crusader Kings III\crashes\ck3_20260715_122142`。
- **崩溃/卡顿根因（2026-07-15 定位，已验证）**：总转换删除了原版数据库对象（宗教 islam_religion 等、文化 somali、文化传承 heritage_*、创新、地理区域、信仰家族 rf_*、特质 fragile_bones），却未覆盖仍在引用它们的原版文件（vassal_stances / succession_laws / scripted_character_templates / script_values / lease_contracts / culture creation_names / doctrine_types）。生成角色无有效 faith/culture → 空 faith 指针(Faith-4294967295)被引擎解引用 → EXCEPTION_ACCESS_VIOLATION；海量 `Failed context switch`/`Invalid religion tag` 报错刷屏 = 卡顿。
- 修复三策略（待用户决策）：A 补 stub 定义被删对象（重、有副作用）；B 覆盖原版引用文件（正、费力）；C 保证角色有有效 faith/culture 止血（针对崩溃）。
- 调试方法论见 `ck3-mod-debug.prompt.md`（增强版排查 prompt）；排查报告见 `debug_report.md`。
- 注意：模组自家宗教 lijiao/beifang/nanfang/xizhouli/dongzhouli 与 culture zhou 均**已定义**，报错只涉及被丢弃的原版对象。

## feudal_admin_government 启用联盟/家族集团（2026-07-16 规划）
- 计划文档：`plan_feudal_admin_confederations.md`。
- 结论速查：`feudal_admin_government` 缺 `government_has_house_blocs` 标志且 `house_aspirations=no`；部落联盟决策在 `dlc_decisions/mpo/` 卡 tribal/nomadic；`mpo_decisions_events.0001` 不限制政府类型可复用；全游戏无 confederation 相关 government_rule；`window_confederation.gui` 游牧/家族集团共用自动适配。
- 用户决策：启用家族宏愿 + 新建专属决议 `copf_call_for_confederation_decision` + 依赖原版 TGP/MPO DLC。
- 实施步骤与质量门见计划文档。
