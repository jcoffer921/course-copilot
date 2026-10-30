import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../static/agent/js/faculty_progress.js", import.meta.url), "utf8");
const { workingMessage, formatElapsed, formatBytes, fileProblem, describeImportError, SLOW_AFTER_SECONDS, VERY_SLOW_AFTER_SECONDS } =
  await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("thresholds are 8 and 90 seconds", () => {
  assert.equal(SLOW_AFTER_SECONDS, 8);
  assert.equal(VERY_SLOW_AFTER_SECONDS, 90);
});

test("formatElapsed uses seconds, then minutes", () => {
  assert.equal(formatElapsed(0), "0s");
  assert.equal(formatElapsed(14), "14s");
  assert.equal(formatElapsed(59), "59s");
  assert.equal(formatElapsed(65), "1m 05s");
  assert.equal(formatElapsed(600), "10m 00s");
});

test("workingMessage escalates from drafting to still working to taking longer", () => {
  assert.equal(workingMessage(0), "Cora is drafting your plan");
  assert.equal(workingMessage(7), "Cora is drafting your plan");
  assert.equal(workingMessage(8), "Still working, 8s");
  assert.equal(workingMessage(14), "Still working, 14s");
  assert.match(workingMessage(90), /taking longer than usual/);
  assert.match(workingMessage(200), /taking longer than usual/);
});

test("formatBytes picks a readable unit", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2 KB");
  assert.equal(formatBytes(1536 * 1024), "1.5 MB");
});

test("fileProblem accepts a normal workbook", () => {
  assert.equal(fileProblem({ name: "reqs.xlsx", size: 4000 }), null);
  assert.equal(fileProblem({ name: "REQS.XLSM", size: 4000 }), null);
});

test("fileProblem names the problem for a wrong type, an empty file, or no file", () => {
  assert.match(fileProblem({ name: "reqs.csv", size: 10 }), /isn't an Excel file/);
  assert.match(fileProblem({ name: "reqs.csv", size: 10 }), /reqs\.csv/);
  assert.match(fileProblem({ name: "empty.xlsx", size: 0 }), /is empty/);
  assert.match(fileProblem(undefined), /No file was selected/);
});

test("describeImportError maps statuses to plain language", () => {
  assert.equal(describeImportError({ status: 400, message: "unsupported file type '.csv'." }), "unsupported file type '.csv'.");
  assert.match(describeImportError({ status: 400, message: "" }), /couldn't be read/);
  assert.match(describeImportError({ status: 403, message: "x" }), /session expired/);
  assert.match(describeImportError({ status: 413, message: "x" }), /too large/);
  assert.match(describeImportError({ status: 429, message: "x" }), /request limit/);
  assert.match(describeImportError({ status: 502, message: "model did not return valid JSON: <raw>" }), /Try again in a moment/);
  assert.doesNotMatch(describeImportError({ status: 502, message: "model did not return valid JSON: <raw>" }), /raw/);
  assert.match(describeImportError(new TypeError("Failed to fetch")), /Couldn't reach the server/);
  assert.equal(describeImportError({ status: 418, message: "teapot" }), "teapot");
});
