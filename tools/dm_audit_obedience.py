#!/usr/bin/env python3
"""Audit the universal-obedience compatibility layer.

This tool is intentionally read-only. It fails closed when a government or a
government_allows = obedience use appears that has not been classified.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


DEFAULT_VANILLA = Path(r"D:\SteamLibrary\steamapps\common\Crusader Kings III\game")
DEFAULT_TIGER_BEFORE = Path(r"D:\Temp\dm_obedience_tiger_before.json")
DEFAULT_TIGER_AFTER = Path(
	r"C:\Users\15550\AppData\Roaming\Code\User\globalStorage"
	r"\unlomtrois.ck3tiger-for-vscode\ck3-tiger\tiger.json"
)

ENABLED_GOVERNMENTS = {
	"feudal_government",
	"republic_government",
	"theocracy_government",
	"clan_government",
	"tribal_government",
	"wanua_government",
	"administrative_government",
	"feudal_admin_government",
	"nomad_government",
	"celestial_government",
	"mandala_government",
	"steppe_admin_government",
	"meritocratic_government",
	"japan_administrative_government",
	"japan_feudal_government",
}

EXCLUDED_GOVERNMENTS = {
	"mercenary_government",
	"holy_order_government",
	"landless_adventurer_government",
	"herder_government",
}

VANILLA_OBEDIENCE_GOVERNMENTS = {
	"nomad_government",
	"steppe_admin_government",
}

OPTION_FLAGS = {
	"dm_obedience_influence",
	"dm_obedience_piety",
	"dm_obedience_republic_gold",
}

LOCALIZATION_KEYS = {
	"DM_OBEDIENCE_INFLUENCE_OPTION",
	"DM_OBEDIENCE_INFLUENCE_OPTION_DESC",
	"DM_OBEDIENCE_PIETY_OPTION",
	"DM_OBEDIENCE_PIETY_OPTION_DESC",
	"DM_OBEDIENCE_REPUBLIC_GOLD_OPTION",
	"DM_OBEDIENCE_REPUBLIC_GOLD_OPTION_DESC",
	"DM_OBEDIENCE_INFLUENCE_SAME_REALM_TT",
	"DM_OBEDIENCE_INFLUENCE_COST",
	"DM_OBEDIENCE_PIETY_COST",
	"DM_OBEDIENCE_BASE_ACCEPTANCE",
	"DM_OBEDIENCE_INFLUENCE_ACCEPTANCE",
	"DM_OBEDIENCE_PIETY_ACCEPTANCE",
	"DM_OBEDIENCE_REPUBLIC_GOLD_ACCEPTANCE",
	"actor_secondary_demand_courtier_interaction",
	"celestial_government_realm",
	"steppe_admin_government_realm",
	"meritocratic_government_realm",
	"japan_administrative_government_realm",
	"japan_feudal_government_realm",
	"game_concept_obedience_threshold_desc",
}

RELEVANT_TIGER_PARTS = {
	r"common\governments\00_government_types.txt",
	r"common\governments\01_japan_government_types.txt",
	r"common\governments\02_government_types_COPF.txt",
	r"common\character_interactions\09_mpo_interactions.txt",
	r"common\character_interactions\zz_dm_obedience_tributary_interactions.txt",
	r"common\casus_belli_types\zz_dm_obedience_mpo_wars.txt",
	r"common\scripted_triggers\zz_dm_obedience_semantic_triggers.txt",
	r"common\script_values\dm_obedience_values.txt",
	r"localization\simp_chinese\replace\dm_obedience_l_simp_chinese.yml",
}


class Audit:
	def __init__(self) -> None:
		self.errors: list[str] = []
		self.notes: list[str] = []

	def require(self, condition: bool, message: str) -> None:
		if not condition:
			self.errors.append(message)

	def note(self, message: str) -> None:
		self.notes.append(message)


def read_text(path: Path) -> str:
	return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def find_object_end(text: str, start: int) -> int:
	depth = 0
	in_string = False
	in_comment = False
	escaped = False
	for index in range(start, len(text)):
		char = text[index]
		if in_comment:
			if char == "\n":
				in_comment = False
			continue
		if in_string:
			if escaped:
				escaped = False
			elif char == "\\":
				escaped = True
			elif char == '"':
				in_string = False
			continue
		if char == "#":
			in_comment = True
		elif char == '"':
			in_string = True
		elif char == "{":
			depth += 1
		elif char == "}":
			depth -= 1
			if depth == 0:
				return index + 1
	raise ValueError("unbalanced object")


def top_level_objects(text: str) -> dict[str, str]:
	objects: dict[str, str] = {}
	pattern = re.compile(r"(?m)^([A-Za-z0-9_]+)\s*=\s*\{")
	position = 0
	while match := pattern.search(text, position):
		end = find_object_end(text, match.start())
		objects[match.group(1)] = text[match.start() : end]
		position = end
	return objects


def named_object(text: str, key: str) -> str:
	match = re.search(rf"(?m)^\t?{re.escape(key)}\s*=\s*\{{", text)
	if not match:
		raise KeyError(key)
	return text[match.start() : find_object_end(text, match.start())]


def balanced(text: str) -> bool:
	try:
		position = 0
		for match in re.finditer(r"(?m)^[A-Za-z0-9_]+\s*=\s*\{", text):
			if match.start() < position:
				continue
			position = find_object_end(text, match.start())
		return True
	except ValueError:
		return False


def government_sources(directory: Path) -> list[Path]:
	return sorted(
		path
		for path in directory.glob("*.txt")
		if not path.name.startswith("_")
	)


def effective_governments(vanilla: Path, mod_root: Path) -> dict[str, tuple[Path, str]]:
	result: dict[str, tuple[Path, str]] = {}
	for path in government_sources(vanilla / "common" / "governments"):
		for key, block in top_level_objects(read_text(path)).items():
			result[key] = (path, block)
	for path in government_sources(mod_root / "common" / "governments"):
		for key, block in top_level_objects(read_text(path)).items():
			result[key] = (path, block)
	return result


def strip_added_obedience(text: str, keys: set[str]) -> str:
	objects = top_level_objects(text)
	for key in keys:
		block = objects[key]
		updated = block.replace("\n\t\tobedience = yes", "", 1)
		if updated == block:
			raise RuntimeError(f"{key}: missing injected obedience line")
		text = text.replace(block, updated, 1)
	return text


def audit_governments(audit: Audit, vanilla: Path, mod_root: Path) -> None:
	effective = effective_governments(vanilla, mod_root)
	known = ENABLED_GOVERNMENTS | EXCLUDED_GOVERNMENTS
	unknown = set(effective) - known
	missing = known - set(effective)
	audit.require(not unknown, f"Unclassified government definitions: {sorted(unknown)}")
	audit.require(not missing, f"Registered government definitions missing: {sorted(missing)}")

	for key in sorted(ENABLED_GOVERNMENTS & set(effective)):
		path, block = effective[key]
		rules = named_object(block, "government_rules")
		count = len(re.findall(r"(?m)^\t\tobedience\s*=\s*yes\s*$", rules))
		audit.require(count == 1, f"{key} in {path}: expected one obedience = yes, found {count}")

	for key in sorted(EXCLUDED_GOVERNMENTS & set(effective)):
		path, block = effective[key]
		rules = named_object(block, "government_rules")
		audit.require(
			not re.search(r"(?m)^\t\tobedience\s*=\s*yes\s*$", rules),
			f"{key} in {path}: excluded government enables obedience",
		)

	vanilla_00 = read_text(vanilla / "common" / "governments" / "00_government_types.txt")
	mod_00_path = mod_root / "common" / "governments" / "00_government_types.txt"
	mod_00 = read_text(mod_00_path)
	mod_00 = mod_00.replace(
		"# Synced from CK3 1.19.0.6. The only intentional changes are documented obedience rules.\n",
		"",
		1,
	)
	mod_00 = strip_added_obedience(
		mod_00,
		(ENABLED_GOVERNMENTS - VANILLA_OBEDIENCE_GOVERNMENTS)
		& set(top_level_objects(mod_00)),
	)
	audit.require(
		mod_00.rstrip() == vanilla_00.rstrip(),
		"00_government_types.txt drifted beyond registered obedience edits",
	)

	vanilla_01 = read_text(vanilla / "common" / "governments" / "01_japan_government_types.txt")
	mod_01_path = mod_root / "common" / "governments" / "01_japan_government_types.txt"
	mod_01 = read_text(mod_01_path)
	mod_01 = mod_01.replace(
		"\t\t# Synced from CK3 1.19.0.6; obedience is the only intentional change in this file.\n",
		"",
		1,
	)
	mod_01 = strip_added_obedience(
		mod_01,
		{"japan_administrative_government", "japan_feudal_government"},
	)
	audit.require(
		mod_01.rstrip() == vanilla_01.rstrip(),
		"01_japan_government_types.txt drifted beyond registered obedience edits",
	)

	for path in (mod_00_path, mod_01_path):
		source = (
			vanilla / "common" / "governments" / path.name
		).read_bytes()
		audit.require(
			path.read_bytes().startswith(b"\xef\xbb\xbf") == source.startswith(b"\xef\xbb\xbf"),
			f"{path}: BOM state differs from vanilla source",
		)


def audit_semantics(audit: Audit, mod_root: Path) -> None:
	trigger_path = mod_root / "common" / "scripted_triggers" / "zz_dm_obedience_semantic_triggers.txt"
	trigger_text = read_text(trigger_path)
	audit.require("dm_original_obedience_government_trigger = {" in trigger_text, "Missing nomad semantic trigger")
	audit.require(
		trigger_text.count("dm_original_obedience_government_trigger = yes") == 2,
		"Succession and peaceful tributary overrides must both use the semantic trigger",
	)

	tributary_path = (
		mod_root
		/ "common"
		/ "character_interactions"
		/ "zz_dm_obedience_tributary_interactions.txt"
	)
	tributary_text = read_text(tributary_path)
	audit.require(
		tributary_text.count("dm_original_obedience_government_trigger = yes") == 2,
		"demand_courtier_interaction must isolate both nomad-only branches",
	)
	audit.require(
		"government_allows = obedience" not in tributary_text,
		"demand_courtier override still uses obedience as a nomad proxy",
	)

	war_path = mod_root / "common" / "casus_belli_types" / "zz_dm_obedience_mpo_wars.txt"
	war_text = read_text(war_path)
	audit.require(
		war_text.count("dm_original_obedience_government_trigger = yes") == 1,
		"retaliation_cb must use the nomad semantic trigger exactly once",
	)
	audit.require("government_allows = obedience" not in war_text, "retaliation_cb still uses obedience as a proxy")

	allowed_mod_path = Path("common/character_interactions/09_mpo_interactions.txt")
	for path in (mod_root / "common").rglob("*.txt"):
		relative = path.relative_to(mod_root)
		if "government_allows = obedience" in read_text(path):
			audit.require(
				relative == allowed_mod_path,
				f"Unclassified mod government_allows = obedience use: {relative}",
			)
	if (mod_root / allowed_mod_path).exists():
		count = read_text(mod_root / allowed_mod_path).count("government_allows = obedience")
		audit.require(count == 4, f"Expected four core interaction obedience gates, found {count}")


def audit_interaction(audit: Audit, mod_root: Path) -> None:
	path = mod_root / "common" / "character_interactions" / "09_mpo_interactions.txt"
	text = read_text(path)
	demand = named_object(text, "mpo_demand_obedience_interaction")
	negotiate = named_object(text, "mpo_negotiate_obedience_interaction")
	audit.require(
		"dread >= medium_dread_value" not in demand,
		"Demand obedience still requires medium dread",
	)
	audit.require(
		"scope:recipient.dm_negotiate_obedience_baseline_acceptance_value" in negotiate,
		"Negotiate obedience does not use the shared acceptance value",
	)
	for flag in OPTION_FLAGS:
		audit.require(
			negotiate.count(f"flag = {flag}") == 1,
			f"{flag}: expected exactly one send option",
		)
		audit.require(
			negotiate.count(f"scope:{flag}") >= 3,
			f"{flag}: option is not paired across validation/acceptance/payment logic",
		)
	audit.require(
		"NOT = { government_has_flag = government_is_republic }" in negotiate,
		"Ordinary gold option is not hidden for republics",
	)
	audit.require(
		"gold = dm_obedience_republic_gold_cost_value" in negotiate,
		"Republic gold is not transferred using the shared double-gold value",
	)
	audit.require(
		"scope:recipient.top_liege = scope:actor.top_liege" in negotiate,
		"Influence option lacks the same-top-realm gate",
	)


def audit_localization(audit: Audit, mod_root: Path) -> None:
	path = (
		mod_root
		/ "localization"
		/ "simp_chinese"
		/ "replace"
		/ "dm_obedience_l_simp_chinese.yml"
	)
	data = path.read_bytes()
	audit.require(data.startswith(b"\xef\xbb\xbf"), f"{path}: localization file must be UTF-8-BOM")
	text = read_text(path)
	keys = re.findall(r"(?m)^ ([A-Za-z0-9_]+):", text)
	for key in LOCALIZATION_KEYS:
		audit.require(keys.count(key) == 1, f"Localization key {key}: expected exactly one definition")
	audit.require("所有启用忠顺机制的领主" in text, "Obedience concept applicability was not corrected")


def diagnostic_fingerprint(item: dict) -> tuple:
	locations = item.get("locations") or [{}]
	primary = locations[0]
	message = item.get("message") or ""
	if item.get("key") == "missing-localization":
		match = re.search(r"localization key ([A-Za-z0-9_.-]+)$", message)
		if match:
			message = f"missing localization key {match.group(1)}"
	return (
		item.get("severity"),
		item.get("key"),
		message,
		(primary.get("path") or "").replace("/", "\\"),
		primary.get("line") or "",
	)


def is_relevant_diagnostic(item: dict) -> bool:
	for location in item.get("locations") or []:
		path = (location.get("path") or "").replace("/", "\\")
		if any(path.endswith(part) for part in RELEVANT_TIGER_PARTS):
			return True
	return False


def audit_tiger(audit: Audit, before: Path, after: Path) -> None:
	if not before.exists() or not after.exists():
		audit.note("Tiger comparison skipped because a baseline or current result is missing")
		return
	before_items = json.loads(before.read_text(encoding="utf-8-sig"))
	after_items = json.loads(after.read_text(encoding="utf-8-sig"))
	before_set = {diagnostic_fingerprint(item) for item in before_items}
	new_items = [
		item
		for item in after_items
		if diagnostic_fingerprint(item) not in before_set
	]
	relevant_new = [item for item in new_items if is_relevant_diagnostic(item)]
	audit.require(
		not relevant_new,
		"Tiger added relevant diagnostics:\n"
		+ "\n".join(
			f"  {item.get('severity')} {item.get('key')}: {item.get('message')}"
			for item in relevant_new[:20]
		),
	)
	audit.note(
		f"Tiger baseline={len(before_items)}, current={len(after_items)}, "
		f"new={len(new_items)}, relevant_new={len(relevant_new)}"
	)


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--vanilla", type=Path, default=DEFAULT_VANILLA)
	parser.add_argument("--tiger-before", type=Path, default=DEFAULT_TIGER_BEFORE)
	parser.add_argument("--tiger-after", type=Path, default=DEFAULT_TIGER_AFTER)
	parser.add_argument("--skip-tiger", action="store_true")
	args = parser.parse_args()

	mod_root = Path(__file__).resolve().parents[1]
	audit = Audit()

	audit_governments(audit, args.vanilla, mod_root)
	audit_semantics(audit, mod_root)
	audit_interaction(audit, mod_root)
	audit_localization(audit, mod_root)

	for relative in (
		"common/scripted_triggers/zz_dm_obedience_semantic_triggers.txt",
		"common/script_values/dm_obedience_values.txt",
		"common/character_interactions/zz_dm_obedience_tributary_interactions.txt",
		"common/casus_belli_types/zz_dm_obedience_mpo_wars.txt",
	):
		path = mod_root / relative
		audit.require(balanced(read_text(path)), f"{relative}: unbalanced braces")

	if not args.skip_tiger:
		audit_tiger(audit, args.tiger_before, args.tiger_after)

	for note in audit.notes:
		print(f"NOTE: {note}")
	if audit.errors:
		for error in audit.errors:
			print(f"ERROR: {error}", file=sys.stderr)
		print(f"FAILED: {len(audit.errors)} obedience audit error(s)", file=sys.stderr)
		return 1
	print("PASS: universal obedience audit")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
