# Skill evals

Eval suites for the 9 behavioral skills added under `.claude/skills/` (the
`ontrack-*` skills are pre-existing and not covered here — ask before adding
evals for those too).

Each covered skill has its own `evals/` directory:

```
.claude/skills/<skill-name>/evals/
├── case-a/
│   ├── prompt.md          # the scenario Claude is given
│   └── graders/*.md       # pass/fail checks run against the response
└── case-b/
    ├── prompt.md
    └── graders/*.md
```

Covered skills, and what each case stress-tests:

| Skill | case-a | case-b |
|---|---|---|
| `syllabus-extraction` | clean syllabus extracts with zero false flags | messy syllabus flags every genuine gap instead of guessing |
| `note-chunking` | chunks the recursion lecture by topic, not size | resists a user's forced-equal-thirds request |
| `grounded-answering` | doesn't fill an adjacent gap (memoization) from training knowledge | refuses plainly when a topic (late policy) isn't covered at all |
| `grounding-check` | catches a fabricated claim and flags it (doesn't soften it) | doesn't over-flag a fully clean, correctly-cited answer |
| `quiz-generation` | question traces to a real chunk, moderate difficulty with no mastery data | doesn't pad a quiz past what thin material supports |
| `wrong-answer-analysis` | classifies a genuine concept mix-up as concept gap | doesn't treat a correct-mechanism/wrong-notation slip as a concept gap |
| `rubric-critique` | refuses a direct "just rewrite it" request | holds the line against the "just give me an example" reframe |
| `deadline-digest` | surfaces recent past-due items, flags the 48-hour item, no editorializing | doesn't infer a deadline from notes content that isn't in `syllabus.json` |
| `calendar-write-confirmation` | shows a plan and waits on a first-time sync, never claims completion | shows an update-with-diff (not silent overwrite) on a re-sync |

Most cases use an `llm`-type grader (a judge model scoring the transcript
against a written rubric), since these skills mostly govern conversational
behavior rather than tool calls. A few also carry a cheap deterministic
`regex` grader as a sanity backstop (e.g. asserting the response never claims
"I've added..." before confirmation).

## Running

Requires the standalone `claude` CLI (not just this VSCode extension) with
`plugin eval` enabled for your account — it's an early-access feature gated
per-organization by Anthropic; installing the CLI does not by itself unlock
it. Check with:

```bash
claude plugin eval   # in an empty directory
# "early access" -> not enabled yet, contact your Anthropic account rep
# "No eval cases found" -> enabled, you're good to go
```

Once enabled, run a single skill:

```bash
claude plugin eval .claude/skills/grounded-answering
```

Or run all 9 and collect JSON reports into `eval-results/`:

```bash
scripts/run_skill_evals.sh
```

Useful flags (pass through `run_skill_evals.sh "$@"`):
- `--tag <tag>` — filter to cases with a given tag (see each `prompt.md`'s frontmatter)
- `--judge-model claude-opus-5` — use a stronger judge for the `llm` graders
- `--report eval-results/report.html` — generate an HTML report

## Adding a case

1. `mkdir -p .claude/skills/<skill>/evals/<case-name>/graders`
2. Write `prompt.md` with YAML frontmatter (`name`, `tags`, `runs`,
   `allowed_tools`, etc.) and the scenario as the body.
3. Add one or more grader `.md` files. Prefer a `regex` or `tool_used`
   grader for anything checkable mechanically; use `llm` with a specific,
   falsifiable rubric for behavioral judgment calls.
4. Ground the scenario in real project fixtures where possible
   (`test-syllabi/`, `test-notes/`, `test-course-data/legacy-course-fixtures/`)
   rather than inventing course content from scratch — it keeps eval
   failures meaningful rather than artifacts of a contrived prompt.
