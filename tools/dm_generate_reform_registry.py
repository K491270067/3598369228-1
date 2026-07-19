"""Generate the deterministic registry and script bridge for the reform system.

The effective law database is assembled in CK3 load order: vanilla first, then
this mod. A mod group with the same key replaces the vanilla group. Generated
files are committed and ``--check`` rejects drift after a game/mod update.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias


ROOT = Path(__file__).resolve().parents[1]
VANILLA = Path(r"D:\SteamLibrary\steamapps\common\Crusader Kings III\game")
MANIFEST = ROOT / "data" / "dm_reform_registry_overrides.toml"
ATOM_RE = re.compile(
	r'"(?:\\.|[^"])*"|[{}]|(?:\?=|!=|>=|<=|==|=)|[^\s{}=<>!?]+|[<>!?]'
)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:.@-]*$")

Value: TypeAlias = str | list[tuple[str | None, "Value"]]
Block: TypeAlias = list[tuple[str | None, Value]]


@dataclass(frozen=True)
class Definition:
	key: str
	block: Block
	source: Path
	layer: str


@dataclass(frozen=True)
class Law:
	key: str
	group: str
	block: Block
	source: Path
	theme: str
	axis: str
	level: int
	is_budget: bool
	group_conditions: Block


def strip_comments(text: str) -> str:
	out: list[str] = []
	quoted = False
	escaped = False
	index = 0
	while index < len(text):
		char = text[index]
		if quoted:
			out.append(char)
			if escaped:
				escaped = False
			elif char == "\\":
				escaped = True
			elif char == '"':
				quoted = False
			index += 1
			continue
		if char == '"':
			quoted = True
			out.append(char)
			index += 1
			continue
		if char == "#":
			while index < len(text) and text[index] not in "\r\n":
				index += 1
			continue
		out.append(char)
		index += 1
	return "".join(out)


def parse_script(text: str, source: Path) -> Block:
	tokens = ATOM_RE.findall(strip_comments(text))
	index = 0

	def parse_block(stop_at_close: bool) -> Block:
		nonlocal index
		items: Block = []
		while index < len(tokens):
			token = tokens[index]
			if token == "}":
				if not stop_at_close:
					raise ValueError(f"{source}: unexpected closing brace")
				index += 1
				return items
			if token == "{":
				index += 1
				items.append((None, parse_block(True)))
				continue
			key = token
			index += 1
			if index >= len(tokens) or tokens[index] not in {"=", "?=", "!=", ">=", "<=", "=="}:
				items.append((None, key))
				continue
			operator = tokens[index]
			index += 1
			if index >= len(tokens):
				raise ValueError(f"{source}: missing value after {key!r}")
			if tokens[index] == "{":
				index += 1
				value: Value = parse_block(True)
			else:
				value = tokens[index]
				index += 1
			stored_key = key if operator == "=" else f"{key} {operator}"
			items.append((stored_key, value))
		if stop_at_close:
			raise ValueError(f"{source}: unclosed block")
		return items

	return parse_block(False)


def read_script(path: Path) -> Block:
	return parse_script(path.read_text(encoding="utf-8-sig", errors="strict"), path)


def values(block: Block, key: str) -> list[Value]:
	return [value for item_key, value in block if item_key == key]


def first(block: Block, key: str) -> Value | None:
	found = values(block, key)
	return found[0] if found else None


def atom(value: Value | None) -> str | None:
	return value if isinstance(value, str) else None


def bool_value(block: Block, key: str) -> bool:
	return atom(first(block, key)) == "yes"


def scalar_assignments(path: Path) -> dict[str, str]:
	assignments: dict[str, str] = {}
	for key, value in read_script(path):
		if key and key.startswith("@") and isinstance(value, str):
			assignments[key] = value
	return assignments


def expand_atoms(value: Value, assignments: dict[str, str]) -> Value:
	if isinstance(value, str):
		seen: set[str] = set()
		while value.startswith("@") and value in assignments and value not in seen:
			seen.add(value)
			value = assignments[value]
		return value
	return [(key, expand_atoms(child, assignments)) for key, child in value]


def script_files(root: Path) -> list[Path]:
	return sorted(
		path
		for path in root.glob("*.txt")
		if not path.name.startswith("_")
		and not path.name.endswith((".bak", ".disabled"))
	)


def layer_definitions(root: Path, layer: str) -> dict[str, Definition]:
	definitions: dict[str, Definition] = {}
	for path in script_files(root):
		assignments = scalar_assignments(path)
		for key, value in read_script(path):
			if not key or key.startswith("@") or not isinstance(value, list):
				continue
			if not IDENT_RE.match(key):
				raise ValueError(f"{path}: invalid top-level key {key!r}")
			definitions[key] = Definition(
				key=key,
				block=expand_atoms(value, assignments),
				source=path,
				layer=layer,
			)
	return definitions


def effective_groups() -> dict[str, Definition]:
	vanilla = layer_definitions(VANILLA / "common" / "laws", "vanilla")
	mod = layer_definitions(ROOT / "common" / "laws", "mod")
	return vanilla | mod


def is_law_candidate(key: str, value: Value) -> bool:
	if not isinstance(value, list) or key.startswith("@"):
		return False
	if key in {
		"default",
		"flag",
		"fallback",
		"law_change_cooldown",
		"law_change_opinion",
		"law_change_opinion_reverse",
		"law_change_obedience",
		"law_change_obedience_reverse",
		"law_change_modifier",
		"law_change_modifier_reverse",
		"tier",
		"triggered_desc",
		"sort_order",
	}:
		return False
	law_markers = {
		"can_have",
		"can_pass",
		"potential",
		"modifier",
		"pass_cost",
		"on_pass",
		"ai_will_do",
		"should_start_with",
		"flag",
	}
	return any(child_key in law_markers for child_key, _ in value)


def collect_laws(manifest: dict) -> tuple[list[Law], list[str]]:
	excluded = set(manifest["settings"]["exclude_groups"])
	budgets = set(manifest["settings"]["budget_groups"])
	group_meta = manifest.get("groups", {})
	groups = effective_groups()
	laws: list[Law] = []
	unknown: list[str] = []
	for group_key in sorted(groups):
		definition = groups[group_key]
		if group_key in excluded:
			continue
		is_budget = group_key in budgets or bool_value(definition.block, "is_treasury_budget_group")
		flags = {atom(value) for value in values(definition.block, "flag")}
		meta = group_meta.get(group_key)
		is_realm = bool(meta) or bool(
			flags
			& {
				"realm_law",
				"succession_order_laws",
				"succession_gender_laws",
				"admin_law",
				"imperial_policy",
			}
		) or is_budget
		if not is_realm:
			continue
		if not meta:
			unknown.append(group_key)
			continue
		children = [
			(key, value)
			for key, value in definition.block
			if key and is_law_candidate(key, value)
		]
		if not children:
			raise ValueError(f"{definition.source}: registered group {group_key} has no laws")
		count = len(children)
		for index, (law_key, block) in enumerate(children):
			assert isinstance(block, list)
			if count == 1:
				level = 0
			else:
				level = round(-3 + (6 * index / (count - 1)))
			laws.append(
				Law(
					key=law_key,
					group=group_key,
					block=block,
					source=definition.source,
					theme=meta["theme"],
					axis=meta["axis"],
					level=max(-3, min(3, level)),
					is_budget=is_budget,
					group_conditions=(
						first(definition.block, "can_change_law_group")
						if isinstance(first(definition.block, "can_change_law_group"), list)
						else []
					),
				)
			)
	if unknown:
		raise ValueError(
			"realm-law groups need explicit metadata overrides: " + ", ".join(unknown)
		)
	law_keys = [law.key for law in laws]
	if len(law_keys) != len(set(law_keys)):
		duplicates = sorted({key for key in law_keys if law_keys.count(key) > 1})
		raise ValueError("duplicate effective law keys: " + ", ".join(duplicates))
	return laws, sorted(groups)


def indent(text: str, tabs: int) -> str:
	prefix = "\t" * tabs
	return "\n".join(prefix + line if line else "" for line in text.splitlines())


def render_value(value: Value, tabs: int = 0) -> str:
	if isinstance(value, str):
		return value
	lines = ["{"]
	for key, child in value:
		if key is None:
			raise ValueError("anonymous values cannot be rendered")
		child_indent = "\t" * (tabs + 1)
		operator = "="
		rendered_key = key
		for candidate in ("?=", "!=", ">=", "<=", "=="):
			suffix = f" {candidate}"
			if key.endswith(suffix):
				rendered_key = key[: -len(suffix)]
				operator = candidate
				break
		if isinstance(child, list):
			lines.append(
				f"{child_indent}{rendered_key} {operator} {render_value(child, tabs + 1)}"
			)
		else:
			lines.append(f"{child_indent}{rendered_key} {operator} {child}")
	current_indent = "\t" * tabs
	lines.append(f"{current_indent}}}")
	return "\n".join(lines)


def resource_cost(law: Law) -> Block:
	value = first(law.block, "pass_cost")
	return value if isinstance(value, list) else []


def block_contains_atom(block: Block, expected: set[str]) -> bool:
	for key, value in block:
		if key in expected:
			return True
		if isinstance(value, str) and value.strip('"') in expected:
			return True
		if isinstance(value, list) and block_contains_atom(value, expected):
			return True
	return False


def strip_powerful_vassal_approval(block: Block) -> Block:
	approval_atoms = {
		"no_powerful_vassal_with_negative_opinion",
		"opposes_succession_law_change_trigger",
	}
	cleaned: Block = []
	for key, value in block:
		if key == "custom_description" and isinstance(value, list):
			if block_contains_atom(value, approval_atoms):
				continue
		if key in approval_atoms:
			continue
		if isinstance(value, list):
			value = strip_powerful_vassal_approval(value)
		cleaned.append((key, value))
	return cleaned


def render_block_entries(block: Block, tabs: int) -> str:
	lines: list[str] = []
	prefix = "\t" * tabs
	for key, value in block:
		if key is None:
			raise ValueError("anonymous values cannot be rendered")
		operator = "="
		rendered_key = key
		for candidate in ("?=", "!=", ">=", "<=", "=="):
			suffix = f" {candidate}"
			if key.endswith(suffix):
				rendered_key = key[: -len(suffix)]
				operator = candidate
				break
		lines.append(f"{prefix}{rendered_key} {operator} {render_value(value, tabs)}")
	return "\n".join(lines)


def law_condition_text(law: Law, keys: tuple[str, ...], tabs: int) -> str:
	blocks: list[Block] = []
	for key in keys:
		value = first(law.block, key)
		if isinstance(value, list):
			blocks.append(strip_powerful_vassal_approval(value))
	if not blocks:
		return ""
	return "\n".join(render_block_entries(block, tabs) for block in blocks if block)


def render_paid_cost_variables(law: Law) -> str:
	lines: list[str] = []
	for resource, value in resource_cost(law):
		if resource not in {"gold", "prestige", "piety", "influence", "legitimacy"}:
			continue
		rendered = render_value(value, 4)
		lines.append(
			f"\t\t\t\tset_variable = {{ name = dm_reform_paid_{resource} value = {rendered} }}"
		)
	return "\n".join(lines)


def render_interaction(law: Law) -> str:
	cost = resource_cost(law)
	cost_text = ""
	if cost:
		cost_text = "\n\tcost = " + render_value(cost, 1)
	shown_conditions = law_condition_text(law, ("potential",), 3)
	valid_parts = []
	if law.group_conditions:
		valid_parts.append(render_block_entries(law.group_conditions, 2))
	law_valid = law_condition_text(law, ("can_have", "can_pass"), 2)
	if law_valid:
		valid_parts.append(law_valid)
	valid_conditions = "\n".join(valid_parts)
	if shown_conditions:
		shown_conditions = "\n" + shown_conditions
	if valid_conditions:
		valid_conditions = "\n" + valid_conditions
	paid_costs = render_paid_cost_variables(law)
	if paid_costs:
		paid_costs = "\n" + paid_costs
	return f"""dm_reform_start_{law.key}_interaction = {{
\tcategory = interaction_category_friendly
\tcommon_interaction = yes
\thidden = yes
\tpopup_on_receive = no
\tai_maybe = no
\tai_accept = {{ base = 100 }}
\tai_targets = {{ ai_recipients = self }}
\tdesc = dm_reform_start_interaction_desc
\ticon = scroll_scales
\t{cost_text.strip()}
\tis_shown = {{
\t\tscope:recipient = scope:actor
\t\tscope:actor = {{
\t\t\tis_ruler = yes
\t\t\tNOT = {{ has_realm_law = {law.key} }}
\t\t\tdm_reform_can_start_trigger = yes{shown_conditions}
\t\t}}
\t}}
\tis_valid_showing_failures_only = {{
\t\tscope:actor = {{
\t\t\tdm_reform_can_start_trigger = yes{valid_conditions}
\t\t}}
\t}}
\ton_accept = {{
\t\tscope:actor = {{
\t\t\tcreate_story = dm_reform_story
\t\t\trandom_owned_story = {{
\t\t\t\tlimit = {{ type = dm_reform_story }}
\t\t\t\tset_variable = {{ name = dm_reform_target value = flag:{law.key} }}
\t\t\t\tset_variable = {{ name = dm_reform_theme value = flag:{law.theme} }}
\t\t\t\tset_variable = {{ name = dm_reform_axis value = flag:{law.axis} }}
\t\t\t\tset_variable = {{ name = dm_reform_target_level value = {law.level} }}
\t\t\t\tset_variable = {{ name = dm_reform_target_is_budget value = {1 if law.is_budget else 0} }}{paid_costs}
\t\t\t\tdm_reform_capture_current_level_effect = yes
\t\t\t}}
\t\t\ttrigger_event = {{ id = dm_reform.0001 days = 1 }}
\t\t}}
\t}}
}}"""


def render_success_effect(laws: list[Law]) -> str:
	lines = [
		"dm_reform_apply_target_law_effect = {",
		"\t# ROOT: reform story",
	]
	for index, law in enumerate(laws):
		command = "if" if index == 0 else "else_if"
		lines.extend(
			[
				f"\t{command} = {{",
				f"\t\tlimit = {{ var:dm_reform_target = flag:{law.key} }}",
				"\t\tstory_owner = {",
				f"\t\t\tadd_realm_law = {law.key}",
				"\t\t}",
				"\t}",
			]
		)
	lines.extend(["\telse = { log = \"DM_REFORM_ERROR: no registered target law\" }", "}", ""])
	lines.extend(
		[
			"dm_reform_capture_current_level_effect = {",
			"\t# ROOT: reform story",
			"\tset_variable = { name = dm_reform_current_level value = 0 }",
		]
	)
	grouped: dict[str, list[Law]] = {}
	for law in laws:
		grouped.setdefault(law.group, []).append(law)
	for index, law in enumerate(laws):
		command = "if" if index == 0 else "else_if"
		lines.extend(
			[
				f"\t{command} = {{",
				f"\t\tlimit = {{ var:dm_reform_target = flag:{law.key} }}",
			]
		)
		for group_law in grouped[law.group]:
			lines.extend(
				[
					"\t\tif = {",
					f"\t\t\tlimit = {{ story_owner = {{ has_realm_law = {group_law.key} }} }}",
					f"\t\t\tset_variable = {{ name = dm_reform_current_level value = {group_law.level} }}",
					"\t\t}",
				]
			)
		lines.extend(["\t}",])
	lines.extend(
		[
			"\tset_variable = {",
			"\t\tname = dm_reform_interest_delta",
			"\t\tvalue = var:dm_reform_target_level",
			"\t}",
			"\tchange_variable = {",
			"\t\tname = dm_reform_interest_delta",
			"\t\tsubtract = var:dm_reform_current_level",
			"\t}",
			"}",
		]
	)
	return "\n".join(lines)


def render_target_valid_trigger(laws: list[Law]) -> str:
	lines = [
		"dm_reform_target_is_not_current_trigger = {",
		"\t# ROOT: reform story",
		"\tOR = {",
	]
	for law in laws:
		lines.extend(
			[
				"\t\tAND = {",
				f"\t\t\tvar:dm_reform_target = flag:{law.key}",
				f"\t\t\tstory_owner = {{ NOT = {{ has_realm_law = {law.key} }} }}",
				"\t\t}",
			]
		)
	lines.extend(["\t}", "}"])
	lines.extend(["", "dm_reform_target_is_valid_trigger = {", "\t# ROOT: reform story", "\tOR = {"])
	for law in laws:
		conditions = []
		if law.group_conditions:
			conditions.append(
				render_block_entries(
					strip_powerful_vassal_approval(law.group_conditions), 4
				)
			)
		law_conditions = law_condition_text(law, ("potential", "can_have"), 4)
		if law_conditions:
			conditions.append(law_conditions)
		rendered_conditions = "\n".join(conditions)
		if rendered_conditions:
			rendered_conditions = "\n" + rendered_conditions
		lines.extend(
			[
				"\t\tAND = {",
				f"\t\t\tvar:dm_reform_target = flag:{law.key}",
				f"\t\t\tstory_owner = {{{rendered_conditions}",
				"\t\t\t}",
				"\t\t}",
			]
		)
	lines.extend(["\t}", "}"])
	return "\n".join(lines)


def registry_json(laws: list[Law]) -> str:
	payload = {
		"schema": 1,
		"vanilla_root": str(VANILLA),
		"laws": [
			{
				"key": law.key,
				"group": law.group,
				"source": str(law.source),
				"source_layer": "mod" if ROOT in law.source.parents else "vanilla",
				"theme": law.theme,
				"axis": law.axis,
				"level": law.level,
				"budget": law.is_budget,
				"cost_resources": [key for key, _ in resource_cost(law) if key],
			}
			for law in laws
		],
	}
	return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


EVENT_CATALOG = [
	("crisis", "军令拒行", "martial"),
	("crisis", "伪诏流传", "intrigue"),
	("crisis", "宗嗣拥旗", "diplomacy"),
	("crisis", "郡县抗命", "stewardship"),
	("crisis", "经义成狱", "learning"),
	("crisis", "宫门鼓噪", "prowess"),
	("crisis", "府库封锁", "stewardship"),
	("setback", "郡县观望", "diplomacy"),
	("setback", "文移壅塞", "stewardship"),
	("setback", "军府争章", "martial"),
	("setback", "谣言入市", "intrigue"),
	("setback", "旧典相难", "learning"),
	("setback", "廷臣托病", "diplomacy"),
	("setback", "驿路迟滞", "prowess"),
	("calm", "灯下定稿", "learning"),
	("calm", "案牍核验", "stewardship"),
	("calm", "密议无声", "intrigue"),
	("calm", "校场推演", "martial"),
	("calm", "温言问策", "diplomacy"),
	("calm", "夜巡宫城", "prowess"),
	("calm", "旧案重读", "learning"),
	("encouragement", "群臣联署", "diplomacy"),
	("encouragement", "廷辩转圜", "learning"),
	("encouragement", "仓廪应令", "stewardship"),
	("encouragement", "军府奉诏", "martial"),
	("encouragement", "密探献策", "intrigue"),
	("encouragement", "宿卫效忠", "prowess"),
	("encouragement", "乡议回暖", "diplomacy"),
	("breakthrough", "障壁自裂", "intrigue"),
	("breakthrough", "大廷定论", "diplomacy"),
	("breakthrough", "新制成章", "learning"),
	("breakthrough", "百司齐动", "stewardship"),
	("breakthrough", "诸军奉行", "martial"),
	("breakthrough", "禁中震服", "prowess"),
	("breakthrough", "四方响应", "diplomacy"),
]

CATEGORY_RULES = {
	"crisis": (-4, -2, 3, 1, 22),
	"setback": (-2, -1, 2, 1, 18),
	"calm": (0, 0, 1, 0, 14),
	"encouragement": (-1, 0, 4, 1, 18),
	"breakthrough": (-2, -1, 7, 2, 22),
}

ATTRIBUTE_TRAITS = {
	"diplomacy": ("gregarious", "just"),
	"martial": ("brave", "strategist"),
	"stewardship": ("diligent", "administrator"),
	"intrigue": ("deceitful", "schemer"),
	"learning": ("scholar", "shrewd"),
	"prowess": ("brave", "strong"),
}


def reform_event_id(index: int) -> int:
	return 1101 + index


def reform_actor_list(category: str) -> str:
	if category in {"crisis", "setback"}:
		return "dm_reform_opponents"
	return "dm_reform_supporters"


def render_reform_event_entry(index: int, category: str, attribute: str) -> str:
	eid = reform_event_id(index)
	fail_progress, fail_support, success_progress, success_support, difficulty = (
		CATEGORY_RULES[category]
	)
	trait_a, trait_b = ATTRIBUTE_TRAITS[attribute]
	next_event = ""
	if index < 25:
		next_event = f"\n\t\t\ttrigger_event = {{ id = dm_reform.{2101 + index} days = 1 }}"
	return f"""dm_reform.{eid} = {{
\ttype = character_event
\ttitle = dm_reform.{eid}.t
\tdesc = dm_reform.{eid}.desc
\ttheme = court_event
\tleft_portrait = scope:dm_reform_actor
\timmediate = {{
\t\tscope:dm_reform_story = {{
\t\t\trandom_in_list = {{
\t\t\t\tvariable = {reform_actor_list(category)}
\t\t\t\tsave_scope_as = dm_reform_actor
\t\t\t}}
\t\t}}
\t\tif = {{
\t\t\tlimit = {{ NOT = {{ exists = scope:dm_reform_actor }} }}
\t\t\troot = {{ save_scope_as = dm_reform_actor }}
\t\t}}
\t}}
\toption = {{
\t\tname = dm_reform.event.measured_response
\t\tcustom_tooltip = dm_reform.event.chance_tt
\t\trandom_list = {{
\t\t\t50 = {{
\t\t\t\tmodifier = {{
\t\t\t\t\tadd = 35
\t\t\t\t\troot = {{ {attribute} >= {difficulty} }}
\t\t\t\t}}
\t\t\t\tmodifier = {{
\t\t\t\t\tadd = 25
\t\t\t\t\tscope:dm_reform_story = {{
\t\t\t\t\t\tdm_reform_has_reformer_trigger = yes
\t\t\t\t\t\tvar:dm_reform_reformer = {{ {attribute} >= {difficulty} }}
\t\t\t\t\t}}
\t\t\t\t}}
\t\t\t\tmodifier = {{
\t\t\t\t\tadd = 10
\t\t\t\t\troot = {{ OR = {{ has_trait = {trait_a} has_trait = {trait_b} }} }}
\t\t\t\t}}
\t\t\t\tscope:dm_reform_story = {{
\t\t\t\t\tchange_variable = {{ name = dm_reform_progress add = {success_progress} }}
\t\t\t\t\tchange_variable = {{ name = dm_reform_support add = {success_support} }}
\t\t\t\t\tset_variable = {{ name = dm_reform_last_result value = flag:success }}
\t\t\t\t}}{next_event}
\t\t\t}}
\t\t\t50 = {{
\t\t\t\tscope:dm_reform_story = {{
\t\t\t\t\tchange_variable = {{ name = dm_reform_progress add = {fail_progress} }}
\t\t\t\t\tchange_variable = {{ name = dm_reform_support add = {fail_support} }}
\t\t\t\t\tset_variable = {{ name = dm_reform_last_result value = flag:failure }}
\t\t\t\t}}{next_event}
\t\t\t}}
\t\t}}
\t}}
\toption = {{
\t\tname = dm_reform.event.costly_response
\t\ttrigger = {{ prestige >= 100 }}
\t\tadd_prestige = -100
\t\tscope:dm_reform_story = {{
\t\t\tchange_variable = {{ name = dm_reform_progress add = {success_progress + 2} }}
\t\t\tchange_variable = {{ name = dm_reform_support add = {max(0, success_support)} }}
\t\t\tset_variable = {{ name = dm_reform_last_result value = flag:great_success }}
\t\t}}{next_event}
\t}}
}}"""


def render_reform_followup(index: int, final: bool) -> str:
	eid = (3101 if final else 2101) + index
	next_text = ""
	if not final:
		next_text = f"\n\t\ttrigger_event = {{ id = dm_reform.{3101 + index} days = 2 }}"
	return f"""dm_reform.{eid} = {{
\ttype = character_event
\ttitle = dm_reform.chain_followup.t
\tdesc = dm_reform.chain_followup.desc
\ttheme = court_event
\tleft_portrait = scope:dm_reform_actor
\toption = {{
\t\tname = dm_reform.chain_followup.a{next_text}
\t}}
}}"""


def render_generated_events() -> str:
	parts = ["namespace = dm_reform", ""]
	for index, (category, _, attribute) in enumerate(EVENT_CATALOG):
		parts.append(render_reform_event_entry(index, category, attribute))
		parts.append("")
	for index in range(25):
		parts.append(render_reform_followup(index, False))
		parts.append("")
		parts.append(render_reform_followup(index, True))
		parts.append("")
	return "\n".join(parts)


def render_event_localization() -> str:
	lines = ["l_simp_chinese:"]
	category_desc = {
		"crisis": "反对者借此事发难，局势已逼近失控。你必须依靠自身或改革者的能力化解危机。",
		"setback": "一名反对者使新制的推行受阻。妥善应对仍可能把阻力转化为进展。",
		"calm": "朝堂暂时平静，这段时间适合校订章程并检验变法的薄弱之处。",
		"encouragement": "支持者带来了好消息，也带来了一个扩大成果的机会。",
		"breakthrough": "长期积累终于打开局面；若能抓住这一刻，新制将大步向前。",
	}
	for index, (category, title, _) in enumerate(EVENT_CATALOG):
		eid = reform_event_id(index)
		lines.append(f' dm_reform.{eid}.t:0 "{title}"')
		lines.append(f' dm_reform.{eid}.desc:0 "{category_desc[category]}"')
	return "\ufeff" + "\n".join(lines) + "\n"


def render_reform_law_buttons(laws: list[Law]) -> str:
	buttons: list[str] = []
	for law in laws:
		if law.is_budget:
			continue
		interaction = f"dm_reform_start_{law.key}_interaction"
		buttons.append(
			f"""button_primary = {{
\t\t\t\t\t\tdatacontext = "[GetPlayer]"
\t\t\t\t\t\tvisible = "[EqualTo_string( SuccessionLawChangeWindow.GetSelectedLaw.GetLaw.GetKey, '{law.key}' )]"
\t\t\t\t\t\tenabled = "[Character.CanSendPlayerInteraction('{interaction}')]"
\t\t\t\t\t\tonclick = "[Character.SendPlayerInteraction('{interaction}')]"
\t\t\t\t\t\ttext = "dm_reform_start_button"
\t\t\t\t\t\tusing = tooltip_above
\t\t\t\t\t\ttooltip = "dm_reform_start_button_tooltip"
\t\t\t\t\t}}"""
		)
	return "\n\n\t\t\t\t\t".join(buttons)


def render_succession_gui(laws: list[Law]) -> str:
	source_path = VANILLA / "gui" / "window_succession_change_law.gui"
	text = source_path.read_text(encoding="utf-8-sig")
	text = text.replace(
		'visible = "[And(SuccessionLawChangeWindow.GetSelectedLaw.ShouldBeApproved, Not( GetPlayer.GetGovernment.HasRule( \'deny_powerful_vassal\' )))]"',
		"visible = no # Powerful-vassal approval is replaced by the reform story.",
		1,
	)
	text = text.replace(
		'visible = "[Not(SuccessionLawChangeWindow.GetSelectedLaw.ShouldBeApproved)]"',
		"visible = yes",
		1,
	)
	text = text.replace(
		'text = "SUCCESSION_LAW_CHANGE_WINDOW_CLAN_TITLE"',
		'text = "dm_reform_law_window_title"',
		1,
	)
	text = text.replace(
		'text = "SUCCESSION_LAW_CHANGE_WINDOW_CLAN_DESC"',
		'text = "dm_reform_law_window_desc"',
		1,
	)
	old_button = """button_primary = {
						enabled = "[SuccessionLawChangeWindow.GetSelectedLaw.CanEnact]"
						onclick = "[SuccessionLawChangeWindow.GetSelectedLaw.Enact]"

						text = "SUCCESSION_LAW_CHANGE_WINDOW_CHANGE"

						using = tooltip_above
						tooltip = "[SuccessionLawChangeWindow.GetSelectedLaw.GetCanEnactDescription]"
					}"""
	new_buttons = render_reform_law_buttons(laws)
	if old_button not in text:
		raise ValueError(f"{source_path}: enact button template changed")
	text = text.replace(old_button, new_buttons, 1)
	return text


def output_files(laws: list[Law]) -> dict[Path, str]:
	header = "# GENERATED by tools/dm_generate_reform_registry.py. DO NOT EDIT.\n\n"
	interactions = (
		header
		+ "\n\n".join(render_interaction(law) for law in laws if not law.is_budget)
		+ "\n"
	)
	effects = header + render_success_effect(laws) + "\n"
	triggers = header + render_target_valid_trigger(laws) + "\n"
	return {
		ROOT / "generated" / "dm_reform_registry.json": registry_json(laws),
		ROOT / "common" / "character_interactions" / "dm_reform_start_interactions_generated.txt": interactions,
		ROOT / "common" / "scripted_effects" / "dm_reform_registry_effects_generated.txt": effects,
		ROOT / "common" / "scripted_triggers" / "dm_reform_registry_triggers_generated.txt": triggers,
		ROOT / "events" / "dm_reform_events_generated.txt": render_generated_events(),
		ROOT
		/ "localization"
		/ "simp_chinese"
		/ "dm_reform_events_generated_l_simp_chinese.yml": render_event_localization(),
		ROOT / "gui" / "window_succession_change_law.gui": render_succession_gui(laws),
	}


def write_or_check(outputs: dict[Path, str], check: bool) -> bool:
	ok = True
	for path, expected in outputs.items():
		if check:
			encoding = "utf-8" if expected.startswith("\ufeff") else "utf-8-sig"
			actual = path.read_text(encoding=encoding) if path.exists() else None
			if actual != expected:
				print(f"DRIFT: {path.relative_to(ROOT)}", file=sys.stderr)
				ok = False
			continue
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(expected, encoding="utf-8", newline="\n")
		print(f"WROTE: {path.relative_to(ROOT)}")
	return ok


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true")
	parser.add_argument("--list", action="store_true")
	args = parser.parse_args()
	if not VANILLA.is_dir():
		raise SystemExit(f"vanilla game root not found: {VANILLA}")
	manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
	laws, _ = collect_laws(manifest)
	if args.list:
		for law in laws:
			print(f"{law.group}\t{law.key}\t{law.theme}\t{law.axis}\t{law.level}")
		print(f"registered laws: {len(laws)}", file=sys.stderr)
		return 0
	outputs = output_files(laws)
	if not write_or_check(outputs, args.check):
		return 1
	print(f"reform registry OK: {len(laws)} laws, {len(outputs)} generated files")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
