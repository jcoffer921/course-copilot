// Pure analysis of a draft plan against its program requirements. No DOM, no imports.
// Credits always come from the program (the grounded source), never from the draft's own numbers.

function programCourses(program) {
  const courses = [];
  for (const category of program?.categories || []) {
    for (const course of category.courses || []) courses.push({ category: category.name, course });
  }
  return courses;
}

function draftSemesters(draft) {
  return Array.isArray(draft?.semesters) ? draft.semesters : [];
}

export function courseCategoryMap(program) {
  const map = {};
  for (const { category, course } of programCourses(program)) map[course.code] = category;
  return map;
}

function creditsByCode(program) {
  const map = {};
  for (const { course } of programCourses(program)) map[course.code] = Number(course.credits) || 0;
  return map;
}

function draftCodes(draft) {
  return draftSemesters(draft).flatMap(semester => (semester.courses || []).map(course => course.code));
}

export function categoryCoverage(draft, program) {
  const planned = new Set(draftCodes(draft));
  return (program?.categories || []).map(category => ({
    name: category.name,
    plannedCredits: (category.courses || [])
      .filter(course => planned.has(course.code))
      .reduce((sum, course) => sum + (Number(course.credits) || 0), 0),
    creditsRequired: Number(category.credits_required) || 0,
  }));
}

export function prerequisiteConflicts(draft, program) {
  const prerequisitesByCode = {};
  for (const { course } of programCourses(program)) prerequisitesByCode[course.code] = course.prerequisites || [];

  const termIndex = {};
  draftSemesters(draft).forEach((semester, index) => {
    for (const course of semester.courses || []) {
      if (!(course.code in termIndex)) termIndex[course.code] = index;
    }
  });

  const conflicts = [];
  draftSemesters(draft).forEach((semester, index) => {
    for (const course of semester.courses || []) {
      for (const prerequisite of prerequisitesByCode[course.code] || []) {
        if (prerequisite in termIndex && termIndex[prerequisite] >= index) {
          conflicts.push({ code: course.code, semesterLabel: semester.label, prerequisite });
        }
      }
    }
  });
  return conflicts;
}

export function planSummary(draft, program) {
  const credits = creditsByCode(program);
  return {
    plannedCredits: draftCodes(draft).reduce((sum, code) => sum + (credits[code] || 0), 0),
    termCount: draftSemesters(draft).length,
    programCredits: Number(program?.total_credits_required) || 0,
    issueCount: prerequisiteConflicts(draft, program).length,
  };
}

export function pluralize(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}


const STARTER_SUGGESTIONS = [
  { label: "4-year plan", prompt: "Create a 4-year plan for a first-year student" },
  { label: "What is still required", prompt: "Which courses are still required after the courses already completed?" },
  { label: "Explain prerequisites", prompt: "Explain the prerequisite sequencing in this plan" },
];
const EVERGREEN_SUGGESTIONS = [
  { label: "Check graduation timeline", prompt: "Does this plan finish on time? Walk through the remaining requirements term by term." },
  { label: "Balance the terms", prompt: "Balance the credits evenly across the terms wherever the prerequisites allow it." },
  { label: "Explain the order", prompt: "Explain why these courses are in this order." },
];
export const HEAVY_TERM_CREDITS = 15;

// Follow-up prompts worth offering next, worked out from the plan on screen (no model call). The list
// leads with real problems (a flagged prerequisite, then the biggest requirement gap, then a heavy
// first term) and is topped up with evergreen options. Never more than `limit`, never a duplicate.
export function suggestFollowUps(draft, program, limit = 3) {
  const terms = draftSemesters(draft);
  if (!terms.some(term => (term.courses || []).length > 0)) return STARTER_SUGGESTIONS.slice(0, limit);

  const picks = [];
  const add = item => { if (!picks.some(pick => pick.label === item.label)) picks.push(item); };

  const handled = new Set();
  for (const conflict of prerequisiteConflicts(draft, program)) {
    if (handled.has(conflict.code)) continue;
    handled.add(conflict.code);
    add({
      label: `Move ${conflict.code} later`,
      prompt: `Move ${conflict.code} to a later term, after ${conflict.prerequisite}, and keep the rest of the plan balanced.`,
    });
  }

  const gaps = categoryCoverage(draft, program)
    .filter(row => row.creditsRequired > 0 && row.plannedCredits < row.creditsRequired)
    .sort((a, b) => (b.creditsRequired - b.plannedCredits) - (a.creditsRequired - a.plannedCredits));
  for (const gap of gaps.slice(0, 2)) {
    add({
      label: `Cover ${gap.name}`,
      prompt: `Add courses to cover the remaining ${gap.name} credits (${gap.plannedCredits} of ${gap.creditsRequired} planned).`,
    });
  }

  const credits = creditsByCode(program);
  const firstTerm = terms.find(term => (term.courses || []).length > 0);
  const firstTermCredits = firstTerm.courses.reduce((sum, course) => sum + (credits[course.code] || 0), 0);
  if (firstTermCredits >= HEAVY_TERM_CREDITS) {
    add({
      label: `Lighten ${firstTerm.label}`,
      prompt: `Lighten ${firstTerm.label} to about 12 credits and move the displaced courses to later terms.`,
    });
  }

  EVERGREEN_SUGGESTIONS.forEach(add);
  return picks.slice(0, limit);
}
