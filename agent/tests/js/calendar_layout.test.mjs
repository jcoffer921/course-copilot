import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../static/agent/js/calendar_layout.js", import.meta.url), "utf8");
const { layoutOverlaps, visibilityForEvent } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("overlapping events receive separate columns", () => {
  const result = layoutOverlaps([
    { id: "a", start_time: "09:00", end_time: "10:30" },
    { id: "b", start_time: "09:30", end_time: "11:00" },
  ]);
  assert.deepEqual(result.map((event) => [event.overlapColumn, event.overlapCount]), [[0, 2], [1, 2]]);
});

test("touching and separate events reuse a column", () => {
  const result = layoutOverlaps([
    { id: "a", start_time: "09:00", end_time: "10:00" },
    { id: "b", start_time: "10:00", end_time: "11:00" },
  ]);
  assert.deepEqual(result.map((event) => [event.overlapColumn, event.overlapCount]), [[0, 1], [0, 1]]);
});

test("an event without an end time uses a one-hour default", () => {
  const [event] = layoutOverlaps([{ id: "a", start_time: "14:00", end_time: null }]);
  assert.equal(event._end - event._start, 60);
});

test("a saved unassigned event enables its matching filter and date", () => {
  const visibility = visibilityForEvent(
    { date: "2026-09-12", course_id: null, type: "other" },
    [{ id: "assignments", types: ["hw", "project"] }, { id: "study", types: ["other"] }],
  );
  assert.deepEqual(visibility, {
    date: "2026-09-12", courseId: null, showUnassigned: true, typeGroupId: "study",
  });
});
