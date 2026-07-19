"""Static acceptance checks for the generated reform system."""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import dm_generate_reform_registry as registry


ROOT = Path(__file__).resolve().parents[1]
REFORM_SCRIPT_FILES = [
	ROOT / "common" / "character_interactions" / "dm_reform_interactions.txt",
	ROOT / "common" / "character_interactions" / "dm_reform_start_interactions_generated.txt",
	ROOT / "common" / "decisions" / "dm_reform_decisions.txt",
	ROOT / "common" / "modifiers" / "dm_reform_modifiers.txt",
	ROOT / "common" / "script_values" / "dm_reform_values.txt",
	ROOT / "common" / "scripted_effects" / "dm_reform_effects.txt",
	ROOT / "common" / "scripted_effects" / "dm_reform_registry_effects_generated.txt",
	ROOT / "common" / "scripted_triggers" / "dm_reform_triggers.txt",
	ROOT / "common" / "scripted_triggers" / "dm_reform_registry_triggers_generated.txt",
	ROOT / "common" / "story_cycles" / "dm_reform_story_cycle.txt",
	ROOT / "events" / "dm_reform_events.txt",
	ROOT / "events" / "dm_reform_events_generated.txt",
]
GUI_FILES = [
	ROOT / "gui" / "window_succession_change_law.gui",
	ROOT / "gui" / "window_treasury_budget_change.gui",
]
LOC_FILES = [
	ROOT / "localization" / "simp_chinese" / "dm_reform_l_simp_chinese.yml",
	ROOT
	/ "localization"
	/ "simp_chinese"
	/ "dm_reform_events_generated_l_simp_chinese.yml",
]
LOC_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+):\d*\s", re.MULTILINE)
EVENT_DEF_RE = re.compile(r"^\s*(dm_reform\.\d+)\s*=\s*\{", re.MULTILINE)
EVENT_REF_RE = re.compile(r"\bid\s*=\s*(dm_reform\.\d+)|trigger_event\s*=\s*(dm_reform\.\d+)")


def fail(message: str) -> None:
	raise AssertionError(message)


def check_balanced(path: Path) -> None:
	text = registry.strip_comments(path.read_text(encoding="utf-8-sig"))
	depth = 0
	quoted = False
	escaped = False
	for index, char in enumerate(text):
		if quoted:
			if escaped:
				escaped = False
			elif char == "\\":
				escaped = True
			elif char == '"':
				quoted = False
			continue
		if char == '"':
			quoted = True
		elif char == "{":
			depth += 1
		elif char == "}":
			depth -= 1
			if depth < 0:
				fail(f"{path}: closing brace underflow at offset {index}")
	if quoted:
		fail(f"{path}: unterminated quote")
	if depth:
		fail(f"{path}: brace depth is {depth}, expected 0")


def check_script_parse() -> None:
	for path in REFORM_SCRIPT_FILES:
		if not path.is_file():
			fail(f"missing reform script: {path}")
		check_balanced(path)
		registry.read_script(path)
		if "set_character_flag" in path.read_text(encoding="utf-8-sig"):
			fail(f"{path}: unknown effect set_character_flag; use add_character_flag")
	for path in GUI_FILES:
		if not path.is_file():
			fail(f"missing reform GUI: {path}")
		check_balanced(path)


def check_event_catalog() -> None:
	texts = [path.read_text(encoding="utf-8-sig") for path in REFORM_SCRIPT_FILES if "events" in path.parts]
	definitions: list[str] = []
	for text in texts:
		definitions.extend(EVENT_DEF_RE.findall(text))
	counts = Counter(definitions)
	duplicates = sorted(key for key, count in counts.items() if count > 1)
	if duplicates:
		fail("duplicate reform event IDs: " + ", ".join(duplicates))
	generated = (ROOT / "events" / "dm_reform_events_generated.txt").read_text(
		encoding="utf-8-sig"
	)
	if len(EVENT_DEF_RE.findall(generated)) != 85:
		fail("generated event catalog must contain exactly 85 nodes")
	if generated.count("add = 3650") != 25:
		fail("the 25 event chains must each record a ten-year repeat cooldown")
	if generated.count("add = 1825") != 10:
		fail("the 10 independent events must each record a five-year repeat cooldown")
	if "root = { save_scope_as = dm_reform_actor }" in generated:
		fail("event actor selection must not substitute the ruler for an invalid actor")
	if generated.count("on_trigger_fail = { trigger_event = dm_reform.0231 }") != 50:
		fail("all 50 event-chain follow-ups must interrupt when their actor is invalid")
	if sum(1 for event in definitions if 1101 <= int(event.split(".")[1]) <= 1135) != 35:
		fail("event catalog must contain exactly 35 entry events")
	references: set[str] = set()
	for text in texts:
		for match in EVENT_REF_RE.finditer(text):
			references.add(match.group(1) or match.group(2))
	missing = sorted(references - set(definitions))
	if missing:
		fail("event references without definitions: " + ", ".join(missing))


def check_localization() -> None:
	keys: list[str] = []
	for path in LOC_FILES:
		if not path.is_file():
			fail(f"missing reform localization: {path}")
		text = path.read_text(encoding="utf-8-sig")
		if not text.startswith("l_simp_chinese:"):
			fail(f"{path}: expected l_simp_chinese header")
		keys.extend(key for key in LOC_KEY_RE.findall(text) if key != "l_simp_chinese")
	counts = Counter(keys)
	duplicates = sorted(key for key, count in counts.items() if count > 1)
	if duplicates:
		fail("duplicate reform localization keys: " + ", ".join(duplicates))
	key_set = set(keys)
	modifier_text = (
		ROOT / "common" / "modifiers" / "dm_reform_modifiers.txt"
	).read_text(encoding="utf-8-sig")
	modifiers = re.findall(r"^([A-Za-z0-9_]+)\s*=\s*\{", modifier_text, re.MULTILINE)
	for modifier in modifiers:
		if modifier not in key_set:
			fail(f"modifier localization missing: {modifier}")
		if f"{modifier}_desc" not in key_set:
			fail(f"modifier description localization missing: {modifier}_desc")


def check_registry_and_gui() -> None:
	result = subprocess.run(
		[sys.executable, str(ROOT / "tools" / "dm_generate_reform_registry.py"), "--check"],
		cwd=ROOT,
		text=True,
		capture_output=True,
		check=False,
	)
	if result.returncode:
		fail(result.stdout + result.stderr)
	interaction_text = (
		ROOT
		/ "common"
		/ "character_interactions"
		/ "dm_reform_start_interactions_generated.txt"
	).read_text(encoding="utf-8-sig")
	for forbidden in (
		"no_powerful_vassal_with_negative_opinion",
		"opposes_succession_law_change_trigger",
	):
		if forbidden in interaction_text:
			fail(f"approval subtree leaked into generated interactions: {forbidden}")
	if interaction_text.count("flag = dm_reform_budget_") != 60:
		fail("budget interaction must contain exactly 60 static combinations")
	if "save_scope_value_as = {" not in interaction_text:
		fail("law costs are not captured in actor scope before story creation")
	if "value = scope:dm_reform_paid_prestige" not in interaction_text:
		fail("captured prestige cost is not copied into the reform story")
	succession_gui = GUI_FILES[0].read_text(encoding="utf-8-sig")
	budget_gui = GUI_FILES[1].read_text(encoding="utf-8-sig")
	if "GetSelectedLaw.Enact" in succession_gui:
		fail("succession/realm-law GUI still calls direct enact")
	if "TreasuryBudgetChangeWindow.EnactBudget]" in budget_gui:
		fail("treasury GUI still calls direct budget enact")
	if "dm_reform_select_reformer_interaction" not in succession_gui:
		fail("law GUI is missing the reformer picker")
	if "dm_reform_select_reformer_interaction" not in budget_gui:
		fail("budget GUI is missing the reformer picker")
	story_text = (
		ROOT / "common" / "story_cycles" / "dm_reform_story_cycle.txt"
	).read_text(encoding="utf-8-sig")
	effects_text = (
		ROOT / "common" / "scripted_effects" / "dm_reform_effects.txt"
	).read_text(encoding="utf-8-sig")
	base_events = (ROOT / "events" / "dm_reform_events.txt").read_text(
		encoding="utf-8-sig"
	)
	if "flag:statements" not in story_text or "dm_reform_statement_days >= 10" not in story_text:
		fail("ten-day participant declaration phase is missing")
	if "days = { 1 7 }" not in effects_text:
		fail("new participants are not scheduled to declare within 1-7 days")
	if "dm_reform.0220 = {" not in base_events:
		fail("participant support/opposition declaration event is missing")
	if "dm_reform_start_opposition_war_effect = {" not in effects_text:
		fail("extreme-failure opposition war effect is missing")
	if "faction_start_war = {}" not in effects_text:
		fail("opposition war outcome does not start a real faction war")


def check_story_assets() -> None:
	story_path = ROOT / "common" / "story_cycles" / "dm_reform_story_cycle.txt"
	story_text = story_path.read_text(encoding="utf-8-sig")
	references = re.findall(r'reference\s*=\s*"([^"]+)"', story_text)
	if not references:
		fail("reform story cycle has no visual asset references")
	for reference in references:
		mod_asset = ROOT / Path(reference)
		vanilla_asset = registry.VANILLA / Path(reference)
		if not mod_asset.exists() and not vanilla_asset.exists():
			fail(f"missing story asset: {reference}")


def main() -> int:
	check_script_parse()
	check_event_catalog()
	check_localization()
	check_registry_and_gui()
	check_story_assets()
	print(
		"reform audit OK: scripts, 85 event nodes, localization, GUI, "
		"60 budgets, story assets"
	)
	return 0


if __name__ == "__main__":
	try:
		raise SystemExit(main())
	except AssertionError as error:
		print(f"REFORM AUDIT FAILED: {error}", file=sys.stderr)
		raise SystemExit(1)
