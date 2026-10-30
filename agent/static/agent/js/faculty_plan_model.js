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

