"""
Grade calculation and CRUD. Pure computation over storage.py's syllabus.json
(grading categories/weights) and grades.json (entered scores) — no
async/API calls here, same boundary as mastery.py.
"""

import uuid

from . import reminders, storage

DEFAULT_GRADE_SCALE = {
    "passing_pct": 60,
    "cutoffs": [
        {"letter": "A", "min_pct": 93}, {"letter": "A-", "min_pct": 90},
        {"letter": "B+", "min_pct": 87}, {"letter": "B", "min_pct": 83}, {"letter": "B-", "min_pct": 80},
        {"letter": "C+", "min_pct": 77}, {"letter": "C", "min_pct": 73}, {"letter": "C-", "min_pct": 70},
        {"letter": "D+", "min_pct": 67}, {"letter": "D", "min_pct": 63}, {"letter": "D-", "min_pct": 60},
    ],
}


class ItemNotFoundError(Exception):
    """Raised when item_id doesn't match any entry in a course's grades.json."""


def _require_syllabus(course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id)
    if syllabus is None:
        raise storage.CourseNotFoundError(f"no syllabus found for '{course_id}'")
    return syllabus


def _letter_for(pct: float, grade_scale: dict) -> str:
    cutoffs = sorted(grade_scale.get("cutoffs") or [], key=lambda c: -c["min_pct"])
    for c in cutoffs:
        if pct >= c["min_pct"]:
            return c["letter"]
    return "F"


def _category_pcts(items: list, component: str) -> list:
    return sorted(i["score"] / i["max_points"] * 100 for i in items if i["component"] == component)


def current_grade(course_id: str, user=None) -> dict:
    """"My grade right now" — categories with zero entered items are
    excluded entirely (not treated as 0%), and the overall percentage is a
    weighted average renormalized across only the categories that have
    data, so an ungraded Final Exam doesn't crater today's number."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id, user=user)["items"]
    grade_scale = syllabus.get("grade_scale") or DEFAULT_GRADE_SCALE

    categories = []
    graded_weight = 0.0
    weighted_sum = 0.0

    for g in grading:
        component = g["component"]
        weight = g.get("weight_pct", 0)
        pcts = _category_pcts(items, component)
        entered_count = len(pcts)
        drop_lowest = g.get("drop_lowest") or 0

        avg_pct = None
        if entered_count > 0:
            d = min(drop_lowest, entered_count - 1)
            kept = pcts[d:]
            avg_pct = round(sum(kept) / len(kept), 2)
            graded_weight += weight
            weighted_sum += weight * avg_pct

        categories.append({
            "component": component, "weight_pct": weight, "avg_pct": avg_pct,
            "entered_count": entered_count, "total_items": g.get("total_items"), "drop_lowest": drop_lowest,
        })

    overall_pct = round(weighted_sum / graded_weight, 2) if graded_weight > 0 else None
    letter = _letter_for(overall_pct, grade_scale) if overall_pct is not None else None

    return {
        "course_id": course_id, "overall_pct": overall_pct, "letter": letter,
        "grade_scale": grade_scale, "categories": categories,
    }


def add_item(course_id: str, component: str, title: str, score: float, max_points: float, date: str = None, user=None) -> dict:
    syllabus = _require_syllabus(course_id)
    valid_components = {g["component"] for g in syllabus.get("grading", [])}
    if component not in valid_components:
        raise ValueError(f"'{component}' isn't a grading category for '{course_id}' (valid: {sorted(valid_components)})")

    data = storage.read_grades(course_id, user=user)
    item = {
        "id": uuid.uuid4().hex, "component": component, "title": title,
        "score": score, "max_points": max_points, "date": date,
    }
    data["items"].append(item)
    errors = storage.validate_grades(data)
    if errors:
        raise ValueError(f"invalid grade item: {'; '.join(errors)}")
    storage.write_grades(course_id, data, user=user)
    return item


def update_item(course_id: str, item_id: str, user=None, **fields) -> dict:
    if "component" in fields:
        syllabus = _require_syllabus(course_id)
        valid_components = {g["component"] for g in syllabus.get("grading", [])}
        if fields["component"] not in valid_components:
            raise ValueError(f"'{fields['component']}' isn't a grading category for '{course_id}' (valid: {sorted(valid_components)})")

    data = storage.read_grades(course_id, user=user)
    for item in data["items"]:
        if item["id"] == item_id:
            for key, value in fields.items():
                if value is not None:
                    item[key] = value
            errors = storage.validate_grades(data)
            if errors:
                raise ValueError(f"invalid grade item: {'; '.join(errors)}")
            storage.write_grades(course_id, data, user=user)
            return item
    raise ItemNotFoundError(f"no grade item '{item_id}' for '{course_id}'")


def delete_item(course_id: str, item_id: str, user=None) -> None:
    data = storage.read_grades(course_id, user=user)
    remaining = [i for i in data["items"] if i["id"] != item_id]
    if len(remaining) == len(data["items"]):
        raise ItemNotFoundError(f"no grade item '{item_id}' for '{course_id}'")
    data["items"] = remaining
    storage.write_grades(course_id, data, user=user)


def find_orphaned_components(course_id: str, new_grading: list, user=None) -> list:
    """Components with entered grade items that would no longer match any
    category in new_grading — a rename or removal would silently orphan
    those items (still visible in the Grades list, but no longer counted
    toward the computed grade)."""
    items = storage.read_grades(course_id, user=user)["items"]
    new_components = {g["component"] for g in new_grading}
    return sorted({i["component"] for i in items if i["component"] not in new_components})


def grade_needed(course_id: str, target_pct: float, user=None) -> dict:
    """Solves the flat score 'p' needed on every remaining ungraded item
    (across every category that has total_items set) to hit target_pct
    overall. A category without total_items is treated as closed — its
    current average (or 0 with no entries at all) is locked in as final,
    and that's flagged in 'notes' since it silently caps the achievable
    grade."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id, user=user)["items"]

    total_weight = sum(g.get("weight_pct", 0) for g in grading) or 100.0
    locked_contribution = 0.0  # A: pct points already locked in, on a 0-100 scale
    remaining_slope = 0.0  # B: pct points contributed per unit of p
    notes = []

    for g in grading:
        component = g["component"]
        weight = g.get("weight_pct", 0)
        total_items = g.get("total_items")
        drop_lowest = g.get("drop_lowest") or 0

        pcts = _category_pcts(items, component)
        entered_count = len(pcts)
        d = min(drop_lowest, max(entered_count - 1, 0))
        kept = pcts[d:]
        kept_sum = sum(kept)
        kept_count = len(kept)

        if total_items is None:
            remaining = 0
            if entered_count == 0:
                notes.append(
                    f"{component} has no items entered and no total_items set — "
                    f"its 0% is currently capping your achievable grade"
                )
        else:
            remaining = max(total_items - entered_count, 0)

        denom = kept_count + remaining
        if denom == 0:
            continue

        locked_contribution += weight * (kept_sum / denom) / total_weight
        remaining_slope += weight * (remaining / denom) / total_weight

    if remaining_slope == 0:
        return {
            "target_pct": target_pct, "locked": True, "p_needed": None,
            "achievable": locked_contribution >= target_pct,
            "ceiling_pct": round(locked_contribution, 2), "notes": notes,
        }

    p_needed = max((target_pct - locked_contribution) / remaining_slope, 0)
    achievable = p_needed <= 100
    ceiling = locked_contribution + remaining_slope * 100

    return {
        "target_pct": target_pct, "locked": False,
        "p_needed": round(p_needed, 2), "achievable": achievable,
        "ceiling_pct": None if achievable else round(ceiling, 2), "notes": notes,
    }


def missable_by_category(course_id: str, target_pct: float, user=None) -> list:
    """Per category (never blended across categories — a missed final exam
    and a missed homework aren't comparable): assuming every other
    remaining item in this category scores 100%, the largest number of
    remaining items that can score 0% while this category's own average
    still meets target_pct."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id, user=user)["items"]

    results = []
    for g in grading:
        component = g["component"]
        total_items = g.get("total_items")
        drop_lowest = g.get("drop_lowest") or 0

        pcts = _category_pcts(items, component)
        entered_count = len(pcts)

        if total_items is None:
            results.append({
                "component": component, "remaining": None, "missable": None,
                "omitted_reason": "total_items not set for this category",
            })
            continue

        remaining = max(total_items - entered_count, 0)
        if remaining == 0:
            results.append({
                "component": component, "remaining": 0, "missable": None,
                "omitted_reason": "no remaining items in this category",
            })
            continue

        d = min(drop_lowest, max(entered_count - 1, 0))
        kept = pcts[d:]
        kept_sum = sum(kept)
        denom = len(kept) + remaining

        best_projected = (kept_sum + remaining * 100) / denom
        if best_projected < target_pct:
            results.append({
                "component": component, "remaining": remaining, "missable": None,
                "omitted_reason": f"target not reachable in this category even at 100% on everything remaining (best possible: {round(best_projected, 2)}%)",
            })
            continue

        missable = 0
        for k in range(remaining, -1, -1):
            projected = (kept_sum + (remaining - k) * 100) / denom
            if projected >= target_pct:
                missable = k
                break

        results.append({"component": component, "remaining": remaining, "missable": missable, "omitted_reason": None})

    return results


def all_courses_summary(user=None) -> dict:
    """Plain average of current_grade() across courses that have at least
    one graded item, following dashboard.build_dashboard()'s per-course
    try/except isolation — one corrupt course doesn't break the rollup for
    the rest."""
    courses = []
    grades_total = 0.0
    graded_count = 0

    for course_id in reminders.list_courses():
        try:
            g = current_grade(course_id, user=user)
            syllabus = storage.read_syllabus(course_id)
            entry = {
                "course_id": course_id, "course_name": syllabus.get("course_name", course_id),
                "current_pct": g["overall_pct"], "letter": g["letter"],
            }
            if g["overall_pct"] is not None:
                grades_total += g["overall_pct"]
                graded_count += 1
        except (storage.SyllabusStorageError, storage.GradesStorageError) as e:
            entry = {"course_id": course_id, "error": str(e)}
        courses.append(entry)

    average_pct = round(grades_total / graded_count, 2) if graded_count > 0 else None
    return {"average_pct": average_pct, "excluded_count": len(courses) - graded_count, "courses": courses}
