import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../static/agent/js/faculty_plan_model.js", import.meta.url), "utf8");
const { suggestFollowUps } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const program = {
  total_credits_required: 120,
  categories: [
    { name: "Core CS", credits_required: 7, courses: [
      { code: "CS 101", title: "Intro", credits: 3, prerequisites: [] },
      { code: "CS 201", title: "Data Structures", credits: 4, prerequisites: ["CS 101"] },
    ] },
    { name: "Mathematics", credits_required: 3, courses: [
      { code: "MATH 230", title: "Discrete", credits: 3, prerequisites: [] },
    ] },
  ],
};

const draft = (...semesters) => ({
  semesters: semesters.map(([label, ...codes]) => ({ label, courses: codes.map(code => ({ code, title: code, credits: 1 })) })),
});

const labels = items => items.map(item => item.label);

test("with no plan yet it offers the three starters", () => {
  const items = suggestFollowUps(null, program);
  assert.deepEqual(labels(items), ["4-year plan", "What is still required", "Explain prerequisites"]);
  assert.ok(items.every(item => item.prompt.length > 10));
});

test("a plan with no courses is treated as no plan", () => {
  assert.deepEqual(labels(suggestFollowUps({ semesters: [{ label: "Fall", courses: [] }] }, program)), ["4-year plan", "What is still required", "Explain prerequisites"]);
  assert.deepEqual(labels(suggestFollowUps({ semesters: [] }, program)), ["4-year plan", "What is still required", "Explain prerequisites"]);
});

test("a flagged prerequisite becomes a fix for that course, first in the list", () => {
  const items = suggestFollowUps(draft(["Fall 2026", "CS 101", "CS 201"]), program);
  assert.equal(items[0].label, "Move CS 201 later");
  assert.match(items[0].prompt, /CS 201/);
  assert.match(items[0].prompt, /CS 101/);
});

test("each conflicting course appears once even if it has several conflicts", () => {
  const program2 = { categories: [{ name: "Core", credits_required: 9, courses: [
    { code: "A 1", credits: 3, prerequisites: [] },
    { code: "B 1", credits: 3, prerequisites: [] },
    { code: "C 1", credits: 3, prerequisites: ["A 1", "B 1"] },
  ] }] };
  const items = suggestFollowUps(draft(["Fall", "A 1", "B 1", "C 1"]), program2);
  assert.equal(labels(items).filter(label => label === "Move C 1 later").length, 1);
});

test("a requirement group with credits still to cover becomes a suggestion", () => {
  const items = suggestFollowUps(draft(["Fall", "CS 101", "CS 201"]), program);
  const gap = items.find(item => item.label.startsWith("Cover"));
  assert.equal(gap.label, "Cover Mathematics");
  assert.match(gap.prompt, /Mathematics/);
  assert.match(gap.prompt, /0 of 3/);
});

test("the largest gap is suggested first", () => {
  const big = { categories: [
    { name: "Small", credits_required: 3, courses: [{ code: "S 1", credits: 3, prerequisites: [] }] },
    { name: "Large", credits_required: 12, courses: [{ code: "L 1", credits: 3, prerequisites: [] }] },
    { name: "Other", credits_required: 3, courses: [{ code: "O 1", credits: 3, prerequisites: [] }] },
  ] };
  const items = suggestFollowUps(draft(["Fall", "O 1"]), big);
  assert.equal(items.find(item => item.label.startsWith("Cover")).label, "Cover Large");
});

test("a heavy first term offers to lighten it, a light one does not", () => {
  const heavy = { categories: [{ name: "Core", credits_required: 15, courses: ["A", "B", "C", "D", "E"].map(code => ({ code, credits: 3, prerequisites: [] })) }] };
  assert.ok(labels(suggestFollowUps(draft(["Fall 2026", "A", "B", "C", "D", "E"]), heavy)).includes("Lighten Fall 2026"));
  assert.ok(!labels(suggestFollowUps(draft(["Fall 2026", "CS 101"]), program)).some(label => label.startsWith("Lighten")));
});

test("it never offers more than three, with no duplicates, and fills with evergreen options", () => {
  const items = suggestFollowUps(draft(["Fall", "CS 101", "CS 201"]), program);
  assert.ok(items.length <= 3);
  assert.equal(new Set(labels(items)).size, items.length);
  const calm = suggestFollowUps(draft(["Fall", "CS 101"], ["Spring", "CS 201", "MATH 230"]), program);
  assert.equal(calm.length, 3);
  assert.ok(labels(calm).includes("Check graduation timeline"));
});

test("a program with no groups and a draft still gets sensible suggestions without throwing", () => {
  const items = suggestFollowUps(draft(["Fall", "X 1"]), { categories: [] });
  assert.ok(items.length >= 2 && items.length <= 3);
  assert.deepEqual(suggestFollowUps(draft(["Fall", "X 1"]), null).length > 0, true);
});
