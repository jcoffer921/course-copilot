import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../static/agent/js/faculty_progress.js", import.meta.url), "utf8");
const { normalizeHeaderLine, HEADER_MAX_LENGTH } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("the cap matches the server's", () => {
  assert.equal(HEADER_MAX_LENGTH, 160);
});

test("whitespace and line breaks fold into single spaces and the ends are trimmed", () => {
  assert.equal(
    normalizeHeaderLine("  The   Pennsylvania\nState \t University  ·  IST \r\n"),
    "The Pennsylvania State University · IST",
  );
});

test("control characters are dropped", () => {
  assert.equal(normalizeHeaderLine("Penn\u0000 State\u0007"), "Penn State");
});

test("bidirectional overrides are dropped", () => {
  assert.equal(normalizeHeaderLine("a‮b"), "ab");
});

test("markup and non-Latin letters are kept as literal text", () => {
  const line = "<b>Penn</b> & Müller Осень";
  assert.equal(normalizeHeaderLine(line), line);
});

test("nothing, or only whitespace, becomes an empty line", () => {
  assert.equal(normalizeHeaderLine(""), "");
  assert.equal(normalizeHeaderLine(null), "");
  assert.equal(normalizeHeaderLine(undefined), "");
  assert.equal(normalizeHeaderLine("   \n\t "), "");
});

test("the length is capped without leaving a trailing space", () => {
  const result = normalizeHeaderLine("word ".repeat(100));
  assert.ok(result.length <= 160);
  assert.equal(result, result.trimEnd());
});
