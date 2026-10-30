import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../static/agent/js/faculty_plan_model.js", import.meta.url), "utf8");
const { courseCategoryMap, categoryCoverage, prerequisiteConflicts, planSummary } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const program = {
  program_name: "B.S. Computer Science",
  total_credits_required: 120,
  categories: [
    { name: "Core", credits_required: 6, courses: [
      { code: "CS 101", title: "Intro", credits: 3, prerequisites: [] },
      { code: "CS 201", title: "Data Structures", credits: 4, prerequisites: ["CS 101"] },
    ] },
    { name: "Math", credits_required: 3, courses: [
      { code: "MATH 230", title: "Discrete", credits: 3, prerequisites: ["MATH 100"] },
    ] },
    { name: "Capstone", credits_required: 6, courses: [] },
  ],
};

const draft = (...semesters) => ({
  semesters: semesters.map(([label, ...codes]) => ({ label, courses: codes.map(code => ({ code, title: code, credits: 99 })) })),
  total_credits: 0,
  notes: "",
});

test("courseCategoryMap maps every code", () => {
  assert.deepEqual(courseCategoryMap(program), { "CS 101": "Core", "CS 201": "Core", "MATH 230": "Math" });
});

test("categoryCoverage sums program credits per category and lists empty categories at zero", () => {
  const result = categoryCoverage(draft(["Fall", "CS 101", "MATH 230"]), program);
  assert.deepEqual(result, [
    { name: "Core", plannedCredits: 3, creditsRequired: 6 },
    { name: "Math", plannedCredits: 3, creditsRequired: 3 },
    { name: "Capstone", plannedCredits: 0, creditsRequired: 6 },
  ]);
});

test("prerequisiteConflicts flags a prerequisite in the same semester", () => {
  const result = prerequisiteConflicts(draft(["Fall", "CS 101", "CS 201"]), program);
  assert.deepEqual(result, [{ code: "CS 201", semesterLabel: "Fall", prerequisite: "CS 101" }]);
});

test("prerequisiteConflicts flags a prerequisite in a later semester", () => {
  const result = prerequisiteConflicts(draft(["Fall", "CS 201"], ["Spring", "CS 101"]), program);
  assert.deepEqual(result, [{ code: "CS 201", semesterLabel: "Fall", prerequisite: "CS 101" }]);
});

test("prerequisiteConflicts passes a prerequisite in an earlier semester", () => {
  assert.deepEqual(prerequisiteConflicts(draft(["Fall", "CS 101"], ["Spring", "CS 201"]), program), []);
});

test("prerequisiteConflicts ignores a prerequisite absent from the draft", () => {
  assert.deepEqual(prerequisiteConflicts(draft(["Fall", "MATH 230"]), program), []);
});

test("prerequisiteConflicts ignores draft courses missing from the program", () => {
  assert.deepEqual(prerequisiteConflicts(draft(["Fall", "ZZ 999", "CS 101"]), program), []);
});

test("planSummary counts conflicts as issueCount", () => {
  const summary = planSummary(draft(["Fall", "CS 101", "CS 201"], ["Spring", "MATH 230"]), program);
  assert.deepEqual(summary, { plannedCredits: 10, termCount: 2, programCredits: 120, issueCount: 1 });
});

test("all functions accept a program with no categories and an empty semesters list", () => {
  const emptyProgram = { categories: [] };
  const emptyDraft = { semesters: [] };
  assert.deepEqual(courseCategoryMap(emptyProgram), {});
  assert.deepEqual(categoryCoverage(emptyDraft, emptyProgram), []);
  assert.deepEqual(prerequisiteConflicts(emptyDraft, emptyProgram), []);
  assert.deepEqual(planSummary(emptyDraft, emptyProgram), { plannedCredits: 0, termCount: 0, programCredits: 0, issueCount: 0 });
  assert.deepEqual(courseCategoryMap(null), {});
  assert.deepEqual(planSummary(null, null), { plannedCredits: 0, termCount: 0, programCredits: 0, issueCount: 0 });
});
