const minutes = (value) => {
  const [hours, minute] = value.split(":").map(Number);
  return hours * 60 + minute;
};

/** Assign side-by-side columns to intersecting timed events. */
export function layoutOverlaps(events) {
  const sorted = events
    .map((event) => ({
      ...event,
      _start: minutes(event.start_time),
      _end: event.end_time ? minutes(event.end_time) : minutes(event.start_time) + 60,
    }))
    .sort((a, b) => a._start - b._start || a._end - b._end);
  const groups = [];
  let group = [];
  let groupEnd = -1;
  sorted.forEach((event) => {
    if (group.length && event._start >= groupEnd) {
      groups.push(group);
      group = [];
      groupEnd = -1;
    }
    group.push(event);
    groupEnd = Math.max(groupEnd, event._end);
  });
  if (group.length) groups.push(group);
  return groups.flatMap((items) => {
    const columns = [];
    items.forEach((event) => {
      let column = columns.findIndex((end) => end <= event._start);
      if (column < 0) column = columns.length;
      columns[column] = event._end;
      event._column = column;
    });
    return items.map((event) => ({ ...event, overlapColumn: event._column, overlapCount: columns.length }));
  });
}

/** Identify the filters and date that must be visible after saving an event. */
export function visibilityForEvent(event, typeGroups) {
  return {
    date: event.date,
    courseId: event.course_id || null,
    showUnassigned: !event.course_id,
    typeGroupId: typeGroups.find((group) => group.types.includes(event.type))?.id || null,
  };
}
