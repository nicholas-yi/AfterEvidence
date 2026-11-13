"""Zero-inference audit of tau2 retail task entities and reference identifiers.

Reads the pinned vendor data as plain JSON. No benchmark runtime, simulator,
or model is used. The output is researcher-facing planning evidence derived
from hidden reference actions: never feed it to an actor, simulator, or memory.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DATA = Path("data/tau2/domains/retail")
TOOLS = Path("src/tau2/domains/retail/tools.py")
DEFAULT_VENDOR = Path(__file__).resolve().parent / "vendor" / "tau2-bench"
WRITE_TOOL = re.compile(r"@is_tool\(ToolType\.WRITE\)\s+def (\w+)")
ID_TABLES = {"user_id": "users", "order_id": "orders", "product_id": "products"}
DEFAULT_EXPOSED = ("0", "1", "2")


def write_tools(source: str) -> frozenset[str]:
    names = frozenset(WRITE_TOOL.findall(source))
    if not names:
        raise ValueError("No write tools found; the pinned tool source layout changed.")
    return names


def _criteria(task: dict[str, Any]) -> dict[str, Any]:
    criteria = task.get("evaluation_criteria")
    if not isinstance(criteria, dict):
        raise ValueError(f"Task {task.get('id')}: missing evaluation criteria.")
    return criteria


def _actions(task: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_criteria(task).get("actions") or [])


def _lookup_customer(action: dict[str, Any], users: dict[str, Any]) -> str | None:
    args = action["arguments"]
    if action["name"] == "find_user_id_by_name_zip":
        matches = [
            user_id
            for user_id, user in users.items()
            if user["name"]["first_name"] == args["first_name"]
            and user["name"]["last_name"] == args["last_name"]
            and user["address"]["zip"] == args["zip"]
        ]
    elif action["name"] == "find_user_id_by_email":
        matches = [user_id for user_id, user in users.items() if user["email"] == args["email"]]
    else:
        return None
    return matches[0] if len(matches) == 1 else None


def task_entities(task: dict[str, Any], db: dict[str, Any]) -> tuple[set[str], set[str]]:
    customers: set[str] = set()
    orders: set[str] = set()
    for action in _actions(task):
        args = action["arguments"]
        if "user_id" in args:
            customers.add(args["user_id"])
        if "order_id" in args:
            orders.add(args["order_id"])
        found = _lookup_customer(action, db["users"])
        if found:
            customers.add(found)
    customers.update(db["orders"][order]["user_id"] for order in orders if order in db["orders"])
    return customers, orders


def invalid_references(task: dict[str, Any], db: dict[str, Any]) -> list[dict[str, object]]:
    items = {item for product in db["products"].values() for item in product["variants"]}
    scenario = json.dumps(task.get("user_scenario"))
    problems: list[dict[str, object]] = []
    for index, action in enumerate(_actions(task), start=1):
        for field, value in action["arguments"].items():
            values = value if isinstance(value, list) else [value]
            if field in ID_TABLES:
                missing = [v for v in values if v not in db[ID_TABLES[field]]]
            elif field in {"item_ids", "new_item_ids"}:
                missing = [v for v in values if v not in items]
            else:
                continue
            for value_missing in missing:
                problems.append(
                    {
                        # 1-based, matching native_scoring's preflight messages.
                        "action": index,
                        "tool": action["name"],
                        "field": field,
                        "value": value_missing,
                        "is_item_id": value_missing in items,
                        # A scripted wrong ID (user told to misstate it) is an intended failed
                        # lookup; an unscripted one points at a reference-artifact defect.
                        "scripted_in_user_instructions": str(value_missing).lstrip("#") in scenario,
                    }
                )
    return problems


def judge_free(criteria: dict[str, Any]) -> bool:
    """True only when every reward-basis component is scorable without an LLM judge."""
    for basis in criteria.get("reward_basis") or []:
        if basis == "DB":
            continue
        if basis == "NL_ASSERTION" and not criteria.get("nl_assertions"):
            continue
        return False
    return True


def _families(ids: list[str], links: dict[str, set[str]]) -> dict[str, str]:
    parent = {task_id: task_id for task_id in ids}

    def find(task_id: str) -> str:
        while parent[task_id] != task_id:
            parent[task_id] = parent[parent[task_id]]
            task_id = parent[task_id]
        return task_id

    by_entity: dict[str, list[str]] = defaultdict(list)
    for task_id in ids:
        for entity in links[task_id]:
            by_entity[entity].append(task_id)
    for members in by_entity.values():
        for other in members[1:]:
            parent[find(other)] = find(members[0])
    roots: dict[str, list[str]] = defaultdict(list)
    for task_id in ids:
        roots[find(task_id)].append(task_id)
    return {task_id: min(members, key=int) for members in roots.values() for task_id in members}


def audit(
    tasks: list[dict[str, Any]],
    split: dict[str, list[str]],
    db: dict[str, Any],
    writes: frozenset[str],
    exposed: tuple[str, ...] = DEFAULT_EXPOSED,
) -> dict[str, Any]:
    by_id = {task["id"]: task for task in tasks}
    train, test = list(split["train"]), list(split["test"])
    entities = {task_id: task_entities(task, db) for task_id, task in by_id.items()}
    test_customers = set().union(*(entities[task_id][0] for task_id in test))
    links = {
        task_id: {f"customer:{c}" for c in entities[task_id][0]}
        | {f"order:{o}" for o in entities[task_id][1]}
        for task_id in train
    }
    family = _families(train, links)
    exposed_families = {family[task_id] for task_id in exposed if task_id in family}

    rows: list[dict[str, Any]] = []
    for task_id in train:
        task = by_id[task_id]
        criteria = _criteria(task)
        customers, orders = entities[task_id]
        row: dict[str, Any] = {
            "task_id": task_id,
            "family": family[task_id],
            "customers": sorted(customers),
            "orders": sorted(orders),
            "writes_in_reference": any(a["name"] in writes for a in _actions(task)),
            "reward_basis": list(criteria.get("reward_basis") or []),
            "nl_assertion_count": len(criteria.get("nl_assertions") or []),
            "judge_free_scoring": judge_free(criteria),
            "invalid_references": invalid_references(task, db),
            "open_upstream_issues": [
                issue["id"] for issue in task.get("issues") or [] if issue.get("status") == "open"
            ],
            "shares_customer_with_test": bool(customers & test_customers),
        }
        reasons = []
        if row["family"] in exposed_families:
            reasons.append("exposed_family")
        if not customers:
            reasons.append("unresolved_customer")
        if row["shares_customer_with_test"]:
            reasons.append("shares_customer_with_test")
        if row["invalid_references"]:
            reasons.append("invalid_reference")
        if row["open_upstream_issues"]:
            reasons.append("open_upstream_issue")
        if not row["writes_in_reference"]:
            reasons.append("no_write_reference")
        if not row["judge_free_scoring"]:
            reasons.append("needs_nl_judge")
        row["exclusion_reasons"] = reasons
        rows.append(row)

    proposed: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: int(r["task_id"])):
        if not row["exclusion_reasons"]:
            proposed.setdefault(row["family"], row["task_id"])

    invalid_all = {
        task_id: problems
        for task_id, task in by_id.items()
        if (problems := invalid_references(task, db))
    }
    sizes = Counter(Counter(family.values()).values())
    return {
        "model_calls": 0,
        "train_tasks": len(train),
        "test_tasks": len(test),
        "train_families": len(set(family.values())),
        "family_size_histogram": {str(k): sizes[k] for k in sorted(sizes)},
        "exposed_tasks": list(exposed),
        "exposed_family_members": sorted(
            (t for t in train if family[t] in exposed_families), key=int
        ),
        "train_tasks_sharing_customer_with_test": sum(r["shares_customer_with_test"] for r in rows),
        "invalid_references_all_splits": invalid_all,
        "exclusion_counts": dict(
            sorted(Counter(reason for r in rows for reason in r["exclusion_reasons"]).items())
        ),
        "eligible_train_tasks": sorted(
            (r["task_id"] for r in rows if not r["exclusion_reasons"]), key=int
        ),
        "proposed_one_per_family": sorted(proposed.values(), key=int),
        "rows": rows,
        "limitations": (
            "Static entity/identifier audit from reference actions. Not a native preflight, "
            "simulator-fidelity check, difficulty estimate, or approval to run inference."
        ),
    }


def load(vendor: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any], str]:
    data = vendor / DATA

    def read(name: str) -> Any:
        return json.loads((data / name).read_text(encoding="utf-8"))

    tools = (vendor / TOOLS).read_text(encoding="utf-8")
    return read("tasks.json"), read("split_tasks.json"), read("db.json"), tools


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit train/test customer overlap and reference identifiers (no model calls)."
    )
    parser.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument("--exposed", nargs="*", default=list(DEFAULT_EXPOSED))
    parser.add_argument("--rows", action="store_true", help="Include per-task rows.")
    args = parser.parse_args()
    tasks, split, db, tools = load(args.vendor)
    report = audit(tasks, split, db, write_tools(tools), tuple(args.exposed))
    if not args.rows:
        report.pop("rows")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
