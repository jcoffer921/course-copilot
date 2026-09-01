function createOnTrackComponent(DCLogic) {
function getCookie(name) {
  if (name === 'csrftoken' && window.OnTrackCsrf) return window.OnTrackCsrf.getToken();
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function readJsonResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  return response.text().then(text => {
    if (response.ok && !text) {
      return { ok: true, status: response.status, data: {} };
    }
    if (contentType.indexOf('application/json') !== -1) {
      return { ok: response.ok, status: response.status, data: text ? JSON.parse(text) : {} };
    }
    const message = response.ok
      ? 'Server returned a non-JSON response.'
      : 'Server returned an HTML error page. Run database migrations if this started after an update, then try again.';
    return { ok: false, status: response.status, data: { detail: message } };
  });
}

function makeClientRequestId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const value = Math.random() * 16 | 0;
    return (c === 'x' ? value : (value & 0x3 | 0x8)).toString(16);
  });
}

function slugify(name) {
  return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}

function isoDateLocal(date) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function addDays(date, days) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() + days);
  return d;
}

function startOfWeek(date) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() - d.getDay());
  return d;
}

function minutesFromTime(value) {
  if (!value) return null;
  const bits = String(value).slice(0, 5).split(':').map(Number);
  if (bits.length !== 2 || isNaN(bits[0]) || isNaN(bits[1])) return null;
  return bits[0] * 60 + bits[1];
}

function normalizeDeadlineType(type) {
  const raw = String(type || 'other').toLowerCase().replace(/[-\s]+/g, '_');
  const map = { assignment: 'hw', homework: 'hw', exam: 'test_quiz', test: 'test_quiz', quiz: 'test_quiz', reading: 'class' };
  const normalized = map[raw] || raw;
  return ['hw', 'project', 'test_quiz', 'class', 'other'].indexOf(normalized) >= 0 ? normalized : 'other';
}

function cleanStudyText(text) {
  const el = document.createElement('textarea');
  el.innerHTML = String(text || '');
  return el.value
    .replace(/<\s*cite\b[^>]*>/gi, '')
    .replace(/<\s*\/\s*cite\s*>/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// Lightweight markdown -> block model for chat bubbles. The template engine
// only supports text interpolation (no raw HTML injection), so instead of
// producing an HTML string, this produces plain data that ontrack.html renders
// with nested sc-for/sc-if.
function normalizeAssistantMarkdown(text) {
  return (text || '')
    .replace(/\\([\\`*_{}\[\]()#+\-.!<>])/g, '$1')
    .replace(/<cite\b[^>]*>/gi, '')
    .replace(/<\/cite>/gi, '');
}

function parseInlineSpans(line) {
  const spans = [];
  const codeStyle = 'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em;background:color-mix(in srgb, var(--color-text) 8%, transparent);border-radius:4px;padding:1px 4px';
  const citeStyle = 'font-size:.95em;color:var(--color-accent-800,var(--color-accent-700))';
  const re = /`([^`]+)`|\*\*(.+?)\*\*|\*(\S(?:.*?\S)?)\*|\[(\d+(?:[-,]\d+)*)\]/g;
  let last = 0, m;
  const addPlain = (text) => {
    if (text) spans.push({ text: text, bold: false, italic: false, isCode: false, isCite: false, isPlain: true });
  };
  while ((m = re.exec(line))) {
    if (m.index > last) addPlain(line.slice(last, m.index));
    if (m[1]) {
      spans.push({ text: m[1], bold: false, italic: false, isCode: true, isCite: false, isPlain: false, style: codeStyle });
    } else if (m[2]) {
      spans.push({ text: m[2], bold: true, italic: false, isCode: false, isCite: false, isPlain: false });
    } else if (m[3]) {
      spans.push({ text: m[3], bold: false, italic: true, isCode: false, isCite: false, isPlain: false });
    } else if (m[4]) {
      spans.push({ text: '[' + m[4] + ']', bold: false, italic: false, isCode: false, isCite: true, isPlain: false, style: citeStyle });
    }
    last = re.lastIndex;
  }
  if (last < line.length) addPlain(line.slice(last));
  if (spans.length === 0) addPlain('');
  return spans;
}

function isTableSeparatorLine(line) {
  return /^\s*\|?(\s*:?-{2,}:?\s*\|)*\s*:?-{2,}:?\s*\|?\s*$/.test(line);
}

function splitTableRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map(c => c.trim());
}

function tableRowGridStyle(colCount) {
  return 'display:grid;grid-template-columns:repeat(' + colCount + ',minmax(0,1fr));';
}

function normalizeMermaidLabel(value) {
  return String(value || '')
    .trim()
    .replace(/^["']|["']$/g, '')
    .replace(/^[A-Za-z0-9_]+\s*(?:\[\s*|\(\s*|\{\s*)/, '')
    .replace(/(?:\s*\]|\s*\)|\s*\})$/, '')
    .trim();
}

function parseMermaidDiagram(code) {
  const rows = [];
  String(code || '').split('\n').forEach(line => {
    const clean = line.trim();
    if (!clean || /^(flowchart|graph)\b/i.test(clean) || /^%%/.test(clean)) return;
    const match = clean.match(/^(.+?)\s*-{1,2}(?:>|-)\s*(.+)$/);
    if (!match) return;
    const from = normalizeMermaidLabel(match[1]);
    const to = normalizeMermaidLabel(match[2]);
    if (from && to) rows.push({ from: from, to: to });
  });
  return rows;
}

function parseVennDiagram(code) {
  const data = { operation: 'union', a: 'A', b: 'B', universe: 'U', caption: '' };
  String(code || '').split('\n').forEach(line => {
    const match = line.match(/^\s*([a-zA-Z_]+)\s*:\s*(.*?)\s*$/);
    if (!match) return;
    const key = match[1].toLowerCase();
    if (Object.prototype.hasOwnProperty.call(data, key) && match[2]) data[key] = match[2];
  });
  const operation = String(data.operation || 'union').toLowerCase().replace(/[-\s]+/g, '_');
  const highlightA = ['union', 'a_minus_b'].indexOf(operation) >= 0;
  const highlightB = ['union', 'b_minus_a'].indexOf(operation) >= 0;
  const highlightOverlap = ['union', 'intersection'].indexOf(operation) >= 0;
  const maskOverlap = ['a_minus_b', 'b_minus_a'].indexOf(operation) >= 0;
  const complementA = operation === 'complement_a';
  return {
    isP: false, isList: false, isTable: false, isHeading: false, isRule: false,
    isDiagram: false, isCodeBlock: false, isVenn: true,
    title: 'Venn Diagram',
    a: data.a || 'A',
    b: data.b || 'B',
    universe: data.universe || 'U',
    caption: data.caption || '',
    stageClass: 'chat-venn-stage' + (complementA ? ' highlight-universe' : ''),
    circleAClass: 'chat-venn-circle a' + (highlightA ? ' highlight' : '') + (complementA ? ' cutout' : ''),
    circleBClass: 'chat-venn-circle b' + (highlightB ? ' highlight' : ''),
    overlapClass: 'chat-venn-overlap' + (highlightOverlap ? ' highlight' : '') + (maskOverlap ? ' mask' : '')
  };
}

function parseMarkdownBlocks(text) {
  const lines = normalizeAssistantMarkdown(text).replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (/^\s*-{3,}\s*$/.test(line)) {
      blocks.push({ isP: false, isList: false, isTable: false, isHeading: false, isRule: true, isDiagram: false, isCodeBlock: false, isVenn: false });
      i++;
      continue;
    }

    const fenceMatch = line.match(/^\s*```([A-Za-z0-9_-]*)\s*$/);
    if (fenceMatch) {
      const language = (fenceMatch[1] || '').toLowerCase();
      const codeLines = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      const code = codeLines.join('\n').trim();
      if (language === 'mermaid') {
        const rows = parseMermaidDiagram(code);
        blocks.push({
          isP: false, isList: false, isTable: false, isHeading: false, isRule: false,
          isDiagram: true, isCodeBlock: false, isVenn: false, title: 'Diagram', code: code, rows: rows,
          hasRows: rows.length > 0
        });
      } else if (language === 'venn') {
        blocks.push(parseVennDiagram(code));
      } else {
        blocks.push({
          isP: false, isList: false, isTable: false, isHeading: false, isRule: false,
          isDiagram: false, isCodeBlock: true, isVenn: false, code: code
        });
      }
      continue;
    }

    const headingMatch = line.match(/^\s{0,3}(#{2,4})\s+(.+?)\s*#*\s*$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const size = level === 2 ? '16px' : level === 3 ? '14.5px' : '13.5px';
      blocks.push({
        isP: false, isList: false, isTable: false, isHeading: true, isRule: false, isDiagram: false, isCodeBlock: false, isVenn: false,
        spans: parseInlineSpans(headingMatch[2]),
        style: 'font-family:var(--font-heading);font-size:' + size + ';font-weight:700;line-height:1.25;margin:10px 0 6px'
      });
      i++;
      continue;
    }

    if (line.trim().startsWith('|') && i + 1 < lines.length && isTableSeparatorLine(lines[i + 1])) {
      const header = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      const gridStyle = tableRowGridStyle(header.length);
      blocks.push({
        isP: false, isList: false, isTable: true, isHeading: false, isRule: false, isDiagram: false, isCodeBlock: false, isVenn: false,
        header: header, rows: rows,
        headerRowStyle: gridStyle + 'background:color-mix(in srgb, var(--color-text) 5%, transparent)',
        dataRowStyle: gridStyle + 'border-top:1px solid var(--color-neutral-200)'
      });
      continue;
    }

    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const itemRe = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
      const items = [];
      while (i < lines.length && itemRe.test(lines[i])) {
        items.push({ spans: parseInlineSpans(lines[i].replace(itemRe, '')) });
        i++;
      }
      blocks.push({ isP: false, isList: true, isOrdered: ordered, isTable: false, isHeading: false, isRule: false, isDiagram: false, isCodeBlock: false, isVenn: false, items: items });
      continue;
    }

    const paraLines = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^\s*-{3,}\s*$/.test(lines[i]) &&
      !/^\s{0,3}#{2,4}\s+/.test(lines[i]) &&
      !/^\s*```[A-Za-z0-9_-]*\s*$/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !(lines[i].trim().startsWith('|') && i + 1 < lines.length && isTableSeparatorLine(lines[i + 1]))
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ isP: true, isList: false, isTable: false, isHeading: false, isRule: false, isDiagram: false, isCodeBlock: false, isVenn: false, spans: parseInlineSpans(paraLines.join(' ')) });
  }
  return blocks;
}

return class Component extends DCLogic {
  state = {
    currentUserEmail: window.CURRENT_USER_EMAIL,
    currentUserName: window.CURRENT_USER_NAME || window.CURRENT_USER_EMAIL,
    currentUsername: window.CURRENT_USERNAME || '',
    notificationsEnabled: false,
    settingsOpen: window.ONTRACK_PAGE_NAME === 'settings', settingsName: '', settingsUsername: '', settingsNotifications: false,
    settingsLoading: false, settingsSaving: false, settingsError: null, calendarConnected: false,
    tab: window.ONTRACK_INITIAL_TAB || 'dashboard', course: window.ONTRACK_INITIAL_COURSE || 'all',
    courseMeta: null, courseDrafts: [], dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
    dashboardSyncingKeys: {}, dashboardSyncError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
    quizStep: 0, quizQuestion: null, quizMcAnswer: null,
    quizOpenAnswer: '', quizStarted: false, quizSetupCount: '5', quizSetupType: 'multiple_choice', quizSetupTopic: 'all', quizSeenQuestions: [],
    quizCorrectCount: 0, quizTargetCount: 5, quizLoading: false, quizError: null, quizErrorSource: null,
    flashcards: [], flashcardIndex: 0, flashcardFlipped: false, flashcardReverse: false,
    flashcardKnown: {}, flashcardStarred: {}, flashcardMode: 'study', flashcardHideMastered: false,
    flashcardCategory: 'all', flashcardSaving: false, flashcardsLoading: false, flashcardsError: null,
    gradesLoading: false, gradesError: null, gradesItems: [], gradesBreakdown: null,
    gradesWhatIfTarget: '', gradesWhatIfLoading: false, gradesWhatIfError: null, gradesWhatIf: null,
    gradesSummaryLoading: false, gradesSummaryError: null, gradesSummary: null,
    addGradeOpen: false, addGradeEditingId: null, addGradeComponent: '', addGradeTitle: '',
    addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '', addGradeLoading: false, addGradeError: null,
    gradingSetupOpen: false, gradingSetupCategoryChoices: [], gradingSetupChecked: {}, gradingSetupFields: {},
    gradingSetupLoading: false, gradingSetupError: null, gradesNotice: null,
    uploadOpenFor: null, uploadLectureId: '', uploadDate: '', uploadFile: null,
    uploadLoading: false, uploadError: null, uploadConflict: null,
    chatMessages: [], chatInput: window.ONTRACK_INITIAL_QUESTION || '', chatLoading: false, chatSending: false, chatError: null, chatCopiedIndex: null,
    chatRetryQuestion: null, chatRetryRequestId: null,
    chatSessionId: null, chatSessions: [], chatSessionsLoading: false, chatSessionsError: null,
    sourceDrawerOpen: false, sourceDrawerLoading: false, sourceDrawerError: null, sourceDrawerCitation: null, sourceDrawerData: null,
    addClassOpen: false, addClassName: '', addClassId: '', addClassIdLocked: false,
    addClassFile: null, addClassLoading: false, addClassError: null,
    uploadPickerOpen: false,
    editingCourseId: null, editingCourseName: '', editCourseError: null,
    deleteCourseId: null, deleteCourseName: '', deleteCourseOpen: false,
    deleteCourseLoading: false, deleteCourseError: null,
    deadlinesLoading: false, deadlinesError: null, allDeadlines: [], deadlineSyncingIds: {}, deadlineSyncError: null,
    calendarView: 'week', calendarSelectedDate: isoDateLocal(new Date()), deadlineCategoryFilters: { hw: true, project: true, test_quiz: true, class: true, other: true },
    deadlineModalOpen: false, deadlineEditingId: null, deadlineReplacingSyllabusKey: null, deadlineCourseId: '', deadlineDate: '',
    deadlineTime: '', deadlineEndTime: '', deadlineTitle: '', deadlineType: 'other', deadlineCompleted: false, deadlineEstimatedEffort: '',
    deadlineModalLoading: false, deadlineModalError: null,
    deadlinePopoverEvent: null, deadlinePopoverStyle: 'display:none',
    currentMinuteTick: Date.now(),
    deleteDeadlineId: null, deleteDeadlineTitle: '', deleteDeadlineOpen: false,
    deleteDeadlineLoading: false, deleteDeadlineError: null,
    notificationsOpen: false, notificationsLoading: false, notifications: [], notificationsUnreadCount: 0, notificationsError: null
  };

  _quizSeq = 0;
  _dashSeq = 0;
  _recentSeq = 0;
  _uploadSeq = 0;
  _chatSeq = 0;
  _sessionsSeq = 0;
  _chatAutoScroll = true;
  _addClassSeq = 0;
  _addGradeSeq = 0;
  _gradesSeq = 0;
  _gradesWhatIfSeq = 0;
  _gradesSummarySeq = 0;
  _gradingSetupSeq = 0;
  _renameSeq = 0;
  _deleteCourseSeq = 0;
  _deadlinesSeq = 0;
  _profileSeq = 0;

  navBtn(active) {
    return {
      display: 'flex', alignItems: 'center', gap: '10px', padding: '9px 12px',
      borderRadius: 'var(--radius-lg)', border: 'none', cursor: 'pointer',
      fontFamily: 'var(--font-body)', fontSize: '14px', fontWeight: active ? 600 : 500,
      textAlign: 'left', width: '100%',
      background: active ? 'var(--color-accent-200)' : 'transparent',
      color: active ? 'var(--color-accent-800)' : 'var(--color-text)'
    };
  }

  courseChip(active) {
    return {
      display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px',
      borderRadius: 'var(--radius-lg)', fontSize: '13px', cursor: 'pointer',
      background: active ? 'var(--color-neutral-200)' : 'transparent',
      fontWeight: active ? 600 : 400
    };
  }

  componentDidMount() {
    this.loadProfile();
    this.loadNotifications();
    this.loadDashboard();
    this.loadDashboardRecent(this.state.course);
    if (this.state.tab === 'deadlines') this.loadAllDeadlines(this.state.course);
    if (this.state.tab === 'grades' && this.state.course === 'all') this.loadGradesSummary();
    window.addEventListener('keydown', this.handleFlashcardKeyDown);
    window.addEventListener('keydown', this.handleDeadlineKeyDown);
    document.addEventListener('mousedown', this.handleDeadlineDocumentMouseDown, true);
    this._deadlineClock = window.setInterval(() => this.setState({ currentMinuteTick: Date.now() }), 60000);
  }

  chatScroller() {
    return document.getElementById('chat-scroll-region');
  }

  chatIsNearBottom() {
    const el = this.chatScroller();
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }

  scrollChatToBottom(force) {
    if (!force && !this._chatAutoScroll) return;
    window.setTimeout(() => {
      const el = this.chatScroller();
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    }, 0);
  }

  handleChatScroll = () => {
    this._chatAutoScroll = this.chatIsNearBottom();
  };

  loadProfile() {
    const seq = ++this._profileSeq;
    this.setState({ settingsLoading: true, settingsError: null });
    fetch('/api/profile/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._profileSeq) return;
        if (!ok) {
          this.setState({ settingsLoading: false, settingsError: data.detail || 'Could not load profile settings.' });
          return;
        }
        this.setState({
          settingsLoading: false,
          currentUserEmail: data.email || this.state.currentUserEmail,
          currentUserName: data.display_name || this.state.currentUserName,
          currentUsername: data.username || this.state.currentUsername,
          notificationsEnabled: !!data.notifications_enabled,
          calendarConnected: !!data.calendar_connected,
        });
      })
      .catch(e => {
        if (seq !== this._profileSeq) return;
        this.setState({ settingsLoading: false, settingsError: 'Network error: ' + e.message });
      });
  }

  loadNotifications() {
    this.setState({ notificationsLoading: true, notificationsError: null });
    fetch('/api/notifications/')
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (!ok) { this.setState({ notificationsLoading: false, notificationsError: data.detail || 'Could not load notifications.' }); return; }
        this.setState({
          notificationsLoading: false,
          notifications: data.notifications || [],
          notificationsUnreadCount: data.unread_count || 0
        });
      })
      .catch(e => this.setState({ notificationsLoading: false, notificationsError: 'Network error: ' + e.message }));
  }

  toggleNotifications() {
    const open = !this.state.notificationsOpen;
    this.setState({ notificationsOpen: open });
    if (open) this.loadNotifications();
  }

  markNotificationsRead(ids) {
    fetch('/api/notifications/read/', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(ids ? { ids: ids } : {})
    })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (!ok) return;
        this.setState({ notifications: data.notifications || [], notificationsUnreadCount: data.unread_count || 0 });
      });
  }

  componentWillUnmount() {
    window.removeEventListener('keydown', this.handleFlashcardKeyDown);
    window.removeEventListener('keydown', this.handleDeadlineKeyDown);
    document.removeEventListener('mousedown', this.handleDeadlineDocumentMouseDown, true);
    if (this._deadlineClock) window.clearInterval(this._deadlineClock);
    if (this._chatCopyTimer) window.clearTimeout(this._chatCopyTimer);
  }

  handleDeadlineKeyDown = (e) => {
    if (e.key === 'Escape' && this.state.deadlinePopoverEvent) {
      this.closeDeadlinePopover();
    }
  };

  handleDeadlineDocumentMouseDown = (e) => {
    if (!this.state.deadlinePopoverEvent) return;
    const target = e.target;
    if (target && target.closest && (target.closest('.deadline-popover') || target.closest('.deadline-event') || target.closest('.deadline-chip'))) return;
    this.closeDeadlinePopover();
  };

  handleFlashcardKeyDown = (e) => {
    if (this.state.tab !== 'flashcards' || this.state.flashcardsLoading || this.state.flashcardsError || !this.state.flashcards.length) return;
    const tag = e.target && e.target.tagName ? e.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.key === ' ') {
      e.preventDefault();
      this.flipFlashcard();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      this.nextFlashcard(this.state.course);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      this.previousFlashcard();
    } else if (e.key.toLowerCase() === 's') {
      e.preventDefault();
      this.toggleFlashcardStar();
    }
  }

  loadDashboard() {
    const seq = ++this._dashSeq;
    this.setState({ dashboardLoading: true, dashboardError: null });
    fetch('/api/dashboard/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._dashSeq) return;
        if (!ok) { this.setState({ dashboardLoading: false, dashboardError: data.detail || 'Could not load dashboard data.' }); return; }
        const realIds = Object.keys(data.courses || {});
        const fallbackId = realIds[0] || (data.drafts && data.drafts[0] && data.drafts[0].course_id) || null;
        const courseSpecific = ['chat', 'progress', 'quiz', 'flashcards', 'grades'].indexOf(this.state.tab) >= 0;
        const targetCourse = this.state.course === 'all' && courseSpecific ? fallbackId : this.state.course;
        this.setState({
          dashboardLoading: false,
          courseMeta: data.courses,
          courseDrafts: data.drafts,
          dashboardDeadlines: data.deadlines,
          dashboardStreak: data.streak,
          course: targetCourse || this.state.course
        });
        if (targetCourse && targetCourse !== 'all') {
          if (this.state.tab === 'chat') this.loadChatSessions(targetCourse);
          if (this.state.tab === 'progress') this.loadDashboardRecent(targetCourse);
          if (this.state.tab === 'flashcards') this.loadFlashcards(targetCourse);
          if (this.state.tab === 'grades') this.loadGrades(targetCourse);
        }
        if (this.state.course === 'all') this.loadDashboardRecent('all');
      })
      .catch(e => {
        if (seq !== this._dashSeq) return;
        this.setState({ dashboardLoading: false, dashboardError: 'Network error: ' + e.message });
      });
  }

  loadDashboardRecent(courseId) {
    const seq = ++this._recentSeq;
    this.setState({ dashboardRecentLoading: true, dashboardRecentError: null });
    const ids = courseId === 'all' ? Object.keys(this.state.courseMeta || {}) : [courseId];
    Promise.all(ids.map(id =>
      fetch(`/api/courses/${id}/quiz/history/?limit=4`)
        .then(r => r.json().then(data => ({ ok: r.ok, data, id })))
    ))
      .then(results => {
        if (seq !== this._recentSeq) return;
        const failed = results.find(r => !r.ok);
        if (failed) { this.setState({ dashboardRecentLoading: false, dashboardRecentError: failed.data.detail || 'Could not load recent activity.' }); return; }
        let attempts = [];
        results.forEach(r => {
          attempts = attempts.concat((r.data.attempts || []).map(a => Object.assign({}, a, { course_id: r.id })));
        });
        attempts.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        this.setState({ dashboardRecentLoading: false, dashboardRecentAttempts: attempts.slice(0, 4) });
      })
      .catch(e => {
        if (seq !== this._recentSeq) return;
        this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message });
      });
  }

  loadAllDeadlines(courseId) {
    const seq = ++this._deadlinesSeq;
    const selectedCourse = courseId || this.state.course;
    const qs = selectedCourse && selectedCourse !== 'all' ? ('?course_id=' + encodeURIComponent(selectedCourse)) : '';
    this.setState({ deadlinesLoading: true, deadlinesError: null });
    fetch('/api/deadlines/' + qs)
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (seq !== this._deadlinesSeq) return;
        if (!ok) { this.setState({ deadlinesLoading: false, deadlinesError: data.detail || 'Could not load deadlines.' }); return; }
        this.setState({ deadlinesLoading: false, allDeadlines: data });
      })
      .catch(e => {
        if (seq !== this._deadlinesSeq) return;
        this.setState({ deadlinesLoading: false, deadlinesError: 'Network error: ' + e.message });
      });
  }

  openAddDeadline() {
    const defaultCourseId = this.state.course && this.state.course !== 'all' ? this.state.course : '';
    this.setState({
      deadlineModalOpen: true, deadlineEditingId: null, deadlineReplacingSyllabusKey: null, deadlineCourseId: defaultCourseId,
      deadlineDate: this.state.calendarSelectedDate || '', deadlineTime: '', deadlineEndTime: '', deadlineTitle: '', deadlineType: 'other', deadlineCompleted: false, deadlineEstimatedEffort: '',
      deadlineModalLoading: false, deadlineModalError: null
    });
  }

  openEditDeadline(event) {
    this.closeDeadlinePopover();
    this.setState({
      deadlineModalOpen: true,
      deadlineEditingId: event.source === 'syllabus' ? null : (event.id || null),
      deadlineReplacingSyllabusKey: event.source === 'syllabus' ? event.key : null,
      deadlineCourseId: event.course_id || '',
      deadlineDate: event.date, deadlineTime: event.time || '', deadlineEndTime: event.end_time || '',
      deadlineTitle: event.title, deadlineType: normalizeDeadlineType(event.type), deadlineCompleted: !!event.completed,
      deadlineEstimatedEffort: event.estimated_effort_minutes ? String(event.estimated_effort_minutes) : '',
      deadlineModalLoading: false, deadlineModalError: null
    });
  }

  openDeadlinePopover(event, browserEvent) {
    if (browserEvent && browserEvent.stopPropagation) browserEvent.stopPropagation();
    const rect = browserEvent && browserEvent.currentTarget && browserEvent.currentTarget.getBoundingClientRect
      ? browserEvent.currentTarget.getBoundingClientRect()
      : { left: 24, right: 24, top: 100, bottom: 140 };
    const width = 320;
    const margin = 12;
    const estimatedHeight = 290;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 768;
    let left = rect.right + margin;
    if (left + width + margin > viewportWidth) left = rect.left - width - margin;
    left = Math.max(margin, Math.min(left, viewportWidth - width - margin));
    let top = rect.top;
    if (top + estimatedHeight + margin > viewportHeight) top = viewportHeight - estimatedHeight - margin;
    top = Math.max(margin, top);
    this.setState({
      deadlinePopoverEvent: event,
      deadlinePopoverStyle: 'left:' + Math.round(left) + 'px;top:' + Math.round(top) + 'px'
    });
  }

  closeDeadlinePopover() {
    this.setState({ deadlinePopoverEvent: null, deadlinePopoverStyle: 'display:none' });
  }

  editDeadlineFromPopover() {
    const event = this.state.deadlinePopoverEvent;
    if (event) this.openEditDeadline(event);
  }

  deleteDeadlineFromPopover() {
    const event = this.state.deadlinePopoverEvent;
    if (event && event.id) this.openDeleteDeadline(event);
  }

  prefillDeadlineModal(deadline) {
    this.setState({
      deadlineModalOpen: true,
      deadlineEditingId: null,
      deadlineReplacingSyllabusKey: null,
      deadlineCourseId: deadline.course_id || (this.state.course !== 'all' ? this.state.course : ''),
      deadlineDate: deadline.date || this.state.calendarSelectedDate || '',
      deadlineTime: deadline.time || '',
      deadlineEndTime: deadline.end_time || '',
      deadlineTitle: deadline.title || '',
      deadlineType: normalizeDeadlineType(deadline.type),
      deadlineCompleted: !!deadline.completed,
      deadlineEstimatedEffort: deadline.estimated_effort_minutes ? String(deadline.estimated_effort_minutes) : '',
      deadlineModalLoading: false,
      deadlineModalError: null
    });
  }

  closeDeadlineModal() {
    this.setState({
      deadlineModalOpen: false, deadlineEditingId: null, deadlineReplacingSyllabusKey: null,
      deadlineModalError: null, deadlineSyncError: null
    });
  }

  submitDeadlineModal() {
    const s = this.state;
    if (!s.deadlineDate || !s.deadlineTitle.trim()) {
      this.setState({ deadlineModalError: 'Date and title are required.' });
      return;
    }
    this.setState({ deadlineModalLoading: true, deadlineModalError: null });
    const body = {
      course_id: s.deadlineCourseId || null,
      date: s.deadlineDate,
      time: s.deadlineTime || null,
      end_time: s.deadlineEndTime || null,
      title: s.deadlineTitle,
      type: s.deadlineType,
      completed: !!s.deadlineCompleted,
      estimated_effort_minutes: s.deadlineEstimatedEffort ? Number(s.deadlineEstimatedEffort) : null
    };
    if (s.deadlineReplacingSyllabusKey) body.replaces_syllabus_key = s.deadlineReplacingSyllabusKey;
    const url = s.deadlineEditingId ? `/api/deadlines/${s.deadlineEditingId}/` : '/api/deadlines/';
    const method = s.deadlineEditingId ? 'PATCH' : 'POST';
    fetch(url, {
      method: method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(body)
    })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (!ok) { this.setState({ deadlineModalLoading: false, deadlineModalError: data.detail || 'Could not save this deadline.' }); return; }
        this.closeDeadlineModal();
        this.loadAllDeadlines();
        this.loadNotifications();
      })
      .catch(e => {
        this.setState({ deadlineModalLoading: false, deadlineModalError: 'Network error: ' + e.message });
      });
  }

  confirmPendingDeadline(deadline, index) {
    const deadlines = Array.isArray(deadline) ? deadline : [deadline];
    const validDeadlines = deadlines.filter(d => d && d.title && d.date);
    if (!validDeadlines.length) return;
    const makeBody = (item) => ({
      course_id: item.course_id || (this.state.course !== 'all' ? this.state.course : null),
      date: item.date,
      time: item.time || null,
      end_time: item.end_time || null,
      title: item.title,
      type: normalizeDeadlineType(item.type),
      completed: !!item.completed
    });
    Promise.all(validDeadlines.map(item =>
      fetch('/api/deadlines/', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(makeBody(item))
      })
        .then(readJsonResponse)
        .then(({ ok, data }) => {
          if (!ok) throw new Error(data.detail || 'Could not add that deadline.');
          return data;
        })
    ))
      .then(() => {
        const messages = this.state.chatMessages.map((m, i) =>
          i === index ? Object.assign({}, m, { pendingDeadline: null, pendingDeadlines: [] }) : m
        );
        const count = validDeadlines.length;
        const text = count > 1
          ? `Added ${count} class meetings to your deadlines calendar.`
          : 'Added it to your deadlines calendar.';
        this.setState({
          chatMessages: messages.concat([{ from: 'assistant', text: text, sources: [], grounded: true }])
        });
        this.scrollChatToBottom();
        this.loadAllDeadlines();
        this.loadDashboard();
        this.loadDashboardRecent(this.state.course);
        this.loadNotifications();
      })
      .catch(e => {
        this.setState({ chatError: e.message });
      });
  }

  dismissPendingDeadline(index) {
    const messages = this.state.chatMessages.map((m, i) =>
      i === index ? Object.assign({}, m, { pendingDeadline: null, pendingDeadlines: [] }) : m
    );
    this.setState({ chatMessages: messages });
  }

  copyChatMessage(text, index) {
    const value = String(text || '');
    const markCopied = () => {
      this.setState({ chatCopiedIndex: index });
      clearTimeout(this._chatCopyTimer);
      this._chatCopyTimer = setTimeout(() => {
        if (this.state.chatCopiedIndex === index) this.setState({ chatCopiedIndex: null });
      }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(markCopied).catch(() => this.copyChatMessageFallback(value, markCopied));
      return;
    }
    this.copyChatMessageFallback(value, markCopied);
  }

  copyChatMessageFallback(text, onDone) {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(area);
    onDone();
  }

  openDeleteDeadline(event) {
    this.setState({
      deadlinePopoverEvent: null,
      deadlinePopoverStyle: 'display:none',
      deleteDeadlineOpen: true,
      deleteDeadlineId: event.id,
      deleteDeadlineTitle: event.title,
      deleteDeadlineError: null,
      deleteDeadlineLoading: false
    });
  }

  closeDeleteDeadline() {
    this.setState({ deleteDeadlineOpen: false, deleteDeadlineId: null, deleteDeadlineTitle: '', deleteDeadlineError: null, deleteDeadlineLoading: false });
  }

  confirmDeleteDeadline() {
    const id = this.state.deleteDeadlineId;
    if (!id || this.state.deleteDeadlineLoading) return;
    this.setState({ deleteDeadlineLoading: true, deleteDeadlineError: null });
    fetch(`/api/deadlines/${id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.detail || 'Could not delete this deadline.');
        this.closeDeleteDeadline();
        this.setState({ deadlinePopoverEvent: null, deadlinePopoverStyle: 'display:none' });
        this.loadAllDeadlines();
        this.loadDashboard();
        this.loadDashboardRecent(this.state.course);
        this.loadNotifications();
      })
      .catch(e => {
        this.setState({ deleteDeadlineLoading: false, deleteDeadlineError: e.message });
      });
  }

  syncDeadlineToCalendar(event) {
    if (this.state.deadlineSyncingIds[event.id]) return;
    this.setState({
      deadlineSyncingIds: Object.assign({}, this.state.deadlineSyncingIds, { [event.id]: true }),
      deadlineSyncError: null
    });
    fetch(`/api/deadlines/${event.id}/calendar-sync/`, { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        const syncing = Object.assign({}, this.state.deadlineSyncingIds);
        delete syncing[event.id];
        if (!ok) { this.setState({ deadlineSyncingIds: syncing, deadlineSyncError: data.detail || 'Could not add to Google Calendar.' }); return; }
        this.setState({ deadlineSyncingIds: syncing });
        this.loadAllDeadlines();
        this.loadNotifications();
      })
      .catch(e => {
        const syncing = Object.assign({}, this.state.deadlineSyncingIds);
        delete syncing[event.id];
        this.setState({ deadlineSyncingIds: syncing, deadlineSyncError: 'Network error: ' + e.message });
      });
  }

  // errorStateKey defaults to 'dashboardSyncError' (the Dashboard tab's own
  // error slot) but the Deadlines tab passes 'deadlineSyncError' instead when
  // syncing a syllabus row from there, so a failure surfaces in whichever tab
  // triggered it rather than only ever landing on the Dashboard's markup.
  // Returns the fetch promise so callers (e.g. the Deadlines tab) can chain
  // a refresh once the request has settled, success or failure.
  addToCalendar(courseId, date, title, type, key, errorStateKey) {
    errorStateKey = errorStateKey || 'dashboardSyncError';
    if (this.state.dashboardSyncingKeys[key]) return Promise.resolve();
    this.setState({
      dashboardSyncingKeys: Object.assign({}, this.state.dashboardSyncingKeys, { [key]: true }),
      [errorStateKey]: null
    });
    return fetch(`/api/courses/${courseId}/calendar-sync/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ date: date, title: title, type: type })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        if (!ok) { this.setState({ dashboardSyncingKeys: syncing, [errorStateKey]: data.detail || 'Could not add to Google Calendar.' }); return; }
        // Scoped by course_id too, not just date+title — on the "all
        // courses" view, two different courses can share an identical
        // date+title (e.g. two "Final" entries the same day), and only
        // the row for the course actually synced should flip to Added.
        const deadlines = this.state.dashboardDeadlines.map(d =>
          (d.course_id === courseId && d.date === date && d.title === title) ? Object.assign({}, d, { synced: true }) : d
        );
        this.setState({ dashboardSyncingKeys: syncing, dashboardDeadlines: deadlines });
      })
      .catch(e => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        this.setState({ dashboardSyncingKeys: syncing, [errorStateKey]: 'Network error: ' + e.message });
      });
  }

  syncDashboardDeadline(event, key) {
    if (!this.state.calendarConnected) return;
    if (event.source === 'syllabus') {
      this.addToCalendar(event.course_id, event.date, event.title, event.type, key);
      return;
    }
    if (!event.id || this.state.dashboardSyncingKeys[key]) return;
    this.setState({
      dashboardSyncingKeys: Object.assign({}, this.state.dashboardSyncingKeys, { [key]: true }),
      dashboardSyncError: null
    });
    fetch(`/api/deadlines/${event.id}/calendar-sync/`, {
      method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }
    })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        if (!ok) {
          this.setState({ dashboardSyncingKeys: syncing, dashboardSyncError: data.detail || 'Could not add this deadline.' });
          return;
        }
        const deadlines = this.state.dashboardDeadlines.map(deadline =>
          deadline.id === event.id ? Object.assign({}, deadline, { synced: true }) : deadline
        );
        this.setState({ dashboardSyncingKeys: syncing, dashboardDeadlines: deadlines });
      })
      .catch(error => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        this.setState({ dashboardSyncingKeys: syncing, dashboardSyncError: 'Network error: ' + error.message });
      });
  }

  loadChatSessions(courseId) {
    const seq = ++this._sessionsSeq;
    this.setState({ chatSessionsLoading: true, chatSessionsError: null });
    fetch(`/api/courses/${courseId}/sessions/`)
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (seq !== this._sessionsSeq) return;
        if (!ok) { this.setState({ chatSessionsLoading: false, chatSessionsError: data.detail || 'Could not load past chats.' }); return; }
        this.setState({ chatSessionsLoading: false, chatSessions: data });
      })
      .catch(e => {
        if (seq !== this._sessionsSeq) return;
        this.setState({ chatSessionsLoading: false, chatSessionsError: 'Network error: ' + e.message });
      });
  }

  openChatSession(courseId, sessionId) {
    const seq = ++this._chatSeq;
    this.setState({
      chatLoading: true, chatError: null, chatCopiedIndex: null,
      chatRetryQuestion: null, chatRetryRequestId: null,
      sourceDrawerOpen: false, sourceDrawerCitation: null, sourceDrawerData: null,
      sourceDrawerError: null
    });
    fetch(`/api/courses/${courseId}/sessions/${sessionId}/`)
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (seq !== this._chatSeq) return;
        if (!ok) { this.setState({ chatLoading: false, chatError: data.detail || 'Could not load that chat.' }); return; }
        const messages = (data.messages || []).map(m => ({
          from: m.role, text: m.content, sources: m.sources || [], grounded: !!m.grounded,
          pendingDeadline: m.pending_deadline || null,
          pendingDeadlines: m.pending_deadlines || []
        }));
        this._chatAutoScroll = true;
        this.setState({
          chatLoading: false, chatSessionId: sessionId, chatMessages: messages, chatInput: '', chatCopiedIndex: null,
          chatRetryQuestion: null, chatRetryRequestId: null, sourceDrawerOpen: false
        });
        this.scrollChatToBottom(true);
      })
      .catch(e => {
        if (seq !== this._chatSeq) return;
        this.setState({ chatLoading: false, chatError: 'Network error: ' + e.message });
      });
  }

  sendChatMessage(courseId, question, options) {
    options = options || {};
    const seq = ++this._chatSeq;
    const requestId = options.requestId || makeClientRequestId();
    const isRetry = !!options.isRetry;
    const shouldFollow = this.chatIsNearBottom();
    this._chatAutoScroll = shouldFollow;
    this.setState({
      chatMessages: isRetry ? this.state.chatMessages : this.state.chatMessages.concat([{ from: 'user', text: question }]),
      chatInput: '', chatSending: true, chatError: null, chatCopiedIndex: null,
      chatRetryQuestion: null, chatRetryRequestId: null
    });
    this.scrollChatToBottom();

    const ask = (sessionId) => {
      fetch(`/api/courses/${courseId}/ask/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ question: question, session_id: sessionId, client_request_id: requestId })
      })
        .then(readJsonResponse)
        .then(({ ok, data }) => {
          if (seq !== this._chatSeq) return;
          if (!ok) {
            this.setState({
              chatSending: false, chatError: data.detail || 'Could not get an answer.',
              chatRetryQuestion: question, chatRetryRequestId: requestId
            });
            return;
          }
          this.setState({
            chatSending: false,
            chatSessionId: sessionId, chatRetryQuestion: null, chatRetryRequestId: null,
            chatMessages: this.state.chatMessages.concat([{
              from: 'assistant', text: data.answer, sources: data.sources || [], grounded: !!data.grounded,
              pendingDeadline: data.pending_deadline || null,
              pendingDeadlines: data.pending_deadlines || []
            }])
          });
          this.scrollChatToBottom();
          this.loadChatSessions(courseId);
        })
        .catch(e => {
          if (seq !== this._chatSeq) return;
          this.setState({
            chatSending: false, chatError: 'Network error: ' + e.message,
            chatRetryQuestion: question, chatRetryRequestId: requestId
          });
        });
    };

    if (this.state.chatSessionId) {
      ask(this.state.chatSessionId);
      return;
    }

    fetch(`/api/courses/${courseId}/sessions/`, {
      method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }
    })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (seq !== this._chatSeq) return;
        if (!ok) {
          this.setState({
            chatSending: false, chatError: data.detail || 'Could not start a new chat.',
            chatRetryQuestion: question, chatRetryRequestId: requestId
          });
          return;
        }
        this.setState({ chatSessionId: data.session_id });
        ask(data.session_id);
      })
      .catch(e => {
        if (seq !== this._chatSeq) return;
        this.setState({
          chatSending: false, chatError: 'Network error: ' + e.message,
          chatRetryQuestion: question, chatRetryRequestId: requestId
        });
      });
  }

  retryChatMessage(courseId) {
    const question = this.state.chatRetryQuestion;
    const requestId = this.state.chatRetryRequestId;
    if (!question || !requestId || this.state.chatSending) return;
    this.sendChatMessage(courseId, question, { isRetry: true, requestId: requestId });
  }

  openSourcePreview(courseId, citation) {
    if (!citation || typeof citation !== 'object') return;
    this.setState({
      sourceDrawerOpen: true, sourceDrawerLoading: true, sourceDrawerError: null,
      sourceDrawerCitation: citation, sourceDrawerData: null
    });
    fetch(`/api/courses/${courseId}/sources/preview/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({
        material_id: citation.material_id,
        material_type: citation.material_type,
        lecture_id: citation.lecture_id || null,
        chunk_id: citation.chunk_id || null,
        url: citation.url || null
      })
    })
      .then(readJsonResponse)
      .then(({ ok, data }) => {
        if (!this.state.sourceDrawerOpen || this.state.sourceDrawerCitation !== citation) return;
        if (!ok) {
          this.setState({ sourceDrawerLoading: false, sourceDrawerError: data.detail || 'Could not inspect this source.' });
          return;
        }
        this.setState({ sourceDrawerLoading: false, sourceDrawerData: data.source, sourceDrawerError: null });
      })
      .catch(error => {
        if (!this.state.sourceDrawerOpen || this.state.sourceDrawerCitation !== citation) return;
        this.setState({ sourceDrawerLoading: false, sourceDrawerError: 'Network error: ' + error.message });
      });
  }

  closeSourcePreview() {
    this.setState({ sourceDrawerOpen: false, sourceDrawerLoading: false, sourceDrawerError: null, sourceDrawerCitation: null, sourceDrawerData: null });
  }

  renameChatSession(courseId, sessionId, currentTitle, event) {
    if (event && event.stopPropagation) event.stopPropagation();
    const title = window.prompt('Rename conversation', currentTitle || 'New chat');
    if (title === null || !title.trim()) return;
    fetch(`/api/courses/${courseId}/sessions/${sessionId}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ title: title.trim() })
    }).then(readJsonResponse).then(({ ok, data }) => {
      if (!ok) { this.setState({ chatSessionsError: data.detail || 'Could not rename that chat.' }); return; }
      this.loadChatSessions(courseId);
    }).catch(error => this.setState({ chatSessionsError: 'Network error: ' + error.message }));
  }

  deleteChatSession(courseId, sessionId, title, event) {
    if (event && event.stopPropagation) event.stopPropagation();
    if (!window.confirm(`Delete “${title || 'this conversation'}”? This cannot be undone.`)) return;
    fetch(`/api/courses/${courseId}/sessions/${sessionId}/`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ confirmation: 'DELETE' })
    }).then(readJsonResponse).then(({ ok, data }) => {
      if (!ok) { this.setState({ chatSessionsError: data.detail || 'Could not delete that chat.' }); return; }
      if (this.state.chatSessionId === sessionId) {
        this.setState({
          chatSessionId: null, chatMessages: [], chatError: null,
          chatRetryQuestion: null, chatRetryRequestId: null, sourceDrawerOpen: false,
          sourceDrawerCitation: null, sourceDrawerData: null, sourceDrawerError: null
        });
      }
      this.loadChatSessions(courseId);
    }).catch(error => this.setState({ chatSessionsError: 'Network error: ' + error.message }));
  }

  loadQuestion(courseId) {
    const seq = ++this._quizSeq;
    const selectedType = this.state.quizSetupType === 'mixed'
      ? ['multiple_choice', 'true_false', 'open_ended'][Math.floor(Math.random() * 3)]
      : this.state.quizSetupType;
    this.setState({ quizLoading: true, quizError: null, quizErrorSource: null, quizQuestion: null, quizMcAnswer: null, quizOpenAnswer: '' });
    const selectedTopic = this.state.quizSetupTopic && this.state.quizSetupTopic !== 'all' ? this.state.quizSetupTopic : null;
    fetch(`/api/courses/${courseId}/quiz/generate/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ mode: 'assessment', question_type: selectedType, topic: selectedTopic, previous_questions: this.state.quizSeenQuestions || [] })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._quizSeq) return;
        if (!ok) { this.setState({ quizLoading: false, quizError: data.detail || 'Could not generate a question.', quizErrorSource: 'generate' }); return; }
        const seen = (this.state.quizSeenQuestions || []).concat([data.question]).slice(-15);
        this.setState({ quizLoading: false, quizQuestion: data, quizSeenQuestions: seen });
      })
      .catch(e => {
        if (seq !== this._quizSeq) return;
        this.setState({ quizLoading: false, quizError: 'Network error: ' + e.message, quizErrorSource: 'generate' });
      });
  }

  startQuiz(courseId) {
    const rawCount = parseInt(this.state.quizSetupCount, 10);
    const count = Math.max(1, Math.min(15, isNaN(rawCount) ? 5 : rawCount));
    this.setState({
      quizStarted: true,
      quizTargetCount: count,
      quizSetupCount: String(count),
      quizStep: 0,
      quizCorrectCount: 0,
      quizQuestion: null,
      quizMcAnswer: null,
      quizOpenAnswer: '',
      quizSeenQuestions: [],
      quizError: null,
      quizErrorSource: null
    }, () => this.loadQuestion(courseId));
  }

  loadFlashcards(courseId) {
    const seq = ++this._quizSeq;
    this.setState({
      flashcardsLoading: true, flashcardsError: null,
      flashcards: [], flashcardIndex: 0, flashcardFlipped: false,
      flashcardKnown: {}, flashcardStarred: {},
    });
    fetch(`/api/courses/${courseId}/flashcards/generate/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ count: 8 })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._quizSeq) return;
        if (!ok) { this.setState({ flashcardsLoading: false, flashcardsError: data.detail || 'Could not generate flashcards.' }); return; }
        const flashcards = (data.flashcards || []).map(card => Object.assign({
          status: 'not_started',
          starred: false,
        }, card, {
          term: cleanStudyText(card.term),
          definition: cleanStudyText(card.definition),
        }));
        this.setState({
          flashcardsLoading: false, flashcards: flashcards, flashcardIndex: 0,
          flashcardFlipped: false, flashcardCategory: 'all'
        });
      })
      .catch(e => {
        if (seq !== this._quizSeq) return;
        this.setState({ flashcardsLoading: false, flashcardsError: 'Network error: ' + e.message });
      });
  }

  flipFlashcard() {
    this.setState({ flashcardFlipped: !this.state.flashcardFlipped });
  }

  flashcardKey(card) {
    if (!card) return '';
    return card.key || ((card.term || '') + '|' + (card.definition || ''));
  }

  flashcardSourceName(card) {
    if (!card) return 'All Categories';
    const source = card.source || 'course';
    if (source === 'web') return 'Web';
    if (source === 'course+web') return 'Course + web';
    return 'Course material';
  }

  flashcardVisibleIndices() {
    const category = this.state.flashcardCategory || 'all';
    const indices = [];
    this.state.flashcards.forEach((card, index) => {
      if (this.state.flashcardHideMastered && card.status === 'mastered') return;
      if (category !== 'all' && this.flashcardSourceName(card) !== category) return;
      indices.push(index);
    });
    return indices;
  }

  currentFlashcardIndex() {
    const visible = this.flashcardVisibleIndices();
    if (!visible.length) return this.state.flashcardIndex;
    return visible.indexOf(this.state.flashcardIndex) >= 0 ? this.state.flashcardIndex : visible[0];
  }

  selectFlashcard(index) {
    if (index < 0 || index >= this.state.flashcards.length) return;
    this.setState({ flashcardIndex: index, flashcardFlipped: false });
  }

  previousFlashcard() {
    const visible = this.flashcardVisibleIndices();
    if (!visible.length) return;
    const pos = visible.indexOf(this.state.flashcardIndex);
    const previousIndex = visible[pos > 0 ? pos - 1 : visible.length - 1];
    this.setState({ flashcardIndex: previousIndex, flashcardFlipped: false });
  }

  nextFlashcard(courseId) {
    const visible = this.flashcardVisibleIndices();
    if (!visible.length) return;
    const pos = visible.indexOf(this.state.flashcardIndex);
    const nextIndex = visible[pos >= 0 && pos + 1 < visible.length ? pos + 1 : 0];
    this.setState({ flashcardIndex: nextIndex, flashcardFlipped: false });
  }

  saveFlashcardProgress(index, patch, advance) {
    const card = this.state.flashcards[index];
    if (!card) return;
    const nextCard = Object.assign({}, card, patch);
    nextCard.term = cleanStudyText(nextCard.term);
    nextCard.definition = cleanStudyText(nextCard.definition);
    const flashcards = this.state.flashcards.slice();
    flashcards[index] = nextCard;
    this.setState({ flashcards: flashcards, flashcardSaving: true, flashcardsError: null });
    fetch(`/api/courses/${this.state.course}/flashcards/progress/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({
        key: nextCard.key,
        term: nextCard.term,
        definition: nextCard.definition,
        status: nextCard.status || 'not_started',
        starred: !!nextCard.starred,
      })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.setState({ flashcardSaving: false, flashcardsError: data.detail || 'Could not save flashcard progress.' });
          return;
        }
        const latest = this.state.flashcards.slice();
        if (latest[index]) {
          latest[index] = Object.assign({}, latest[index], {
            key: data.key || latest[index].key,
            status: data.status || latest[index].status || 'not_started',
            starred: !!data.starred,
          });
        }
        this.setState({ flashcards: latest, flashcardSaving: false }, () => {
          if (advance) this.nextFlashcard(this.state.course);
        });
      })
      .catch(e => {
        this.setState({ flashcardSaving: false, flashcardsError: 'Network error: ' + e.message });
      });
  }

  markFlashcardKnown(known) {
    const index = this.currentFlashcardIndex();
    const card = this.state.flashcards[index];
    if (!card) return;
    this.saveFlashcardProgress(index, { status: known ? 'mastered' : 'in_progress' }, true);
  }

  toggleFlashcardStar() {
    const index = this.currentFlashcardIndex();
    const card = this.state.flashcards[index];
    if (!card) return;
    this.saveFlashcardProgress(index, { starred: !card.starred }, false);
  }

  shuffleFlashcards() {
    const cards = this.state.flashcards.slice();
    for (let i = cards.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const tmp = cards[i];
      cards[i] = cards[j];
      cards[j] = tmp;
    }
    this.setState({ flashcards: cards, flashcardIndex: 0, flashcardFlipped: false });
  }

  toggleFlashcardDirection() {
    this.setState({ flashcardReverse: !this.state.flashcardReverse, flashcardFlipped: false });
  }

  toggleFlashcardHideMastered() {
    this.setState({ flashcardHideMastered: !this.state.flashcardHideMastered, flashcardIndex: 0, flashcardFlipped: false });
  }

  resetFlashcardProgress() {
    const keys = this.state.flashcards.map(card => this.flashcardKey(card)).filter(Boolean);
    this.setState({ flashcardSaving: true, flashcardsError: null });
    fetch(`/api/courses/${this.state.course}/flashcards/progress/reset/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ keys: keys })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.setState({ flashcardSaving: false, flashcardsError: data.detail || 'Could not reset flashcard progress.' });
          return;
        }
        const flashcards = this.state.flashcards.map(card => Object.assign({}, card, { status: 'not_started' }));
        this.setState({ flashcards: flashcards, flashcardSaving: false, flashcardIndex: 0, flashcardFlipped: false });
      })
      .catch(e => {
        this.setState({ flashcardSaving: false, flashcardsError: 'Network error: ' + e.message });
      });
  }

  loadGrades(courseId) {
    const seq = ++this._gradesSeq;
    this.setState({ gradesLoading: true, gradesError: null });
    fetch(`/api/courses/${courseId}/grades/`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesSeq) return;
        if (!ok) { this.setState({ gradesLoading: false, gradesError: data.detail || 'Could not load grades.' }); return; }
        const defaultTarget = (data.grade.grade_scale && data.grade.grade_scale.passing_pct) || 60;
        this.setState({
          gradesLoading: false, gradesItems: data.items, gradesBreakdown: data.grade,
          gradesWhatIfTarget: this.state.gradesWhatIfTarget || String(defaultTarget),
        });
        this.loadGradesWhatIf(courseId);
      })
      .catch(e => {
        if (seq !== this._gradesSeq) return;
        this.setState({ gradesLoading: false, gradesError: 'Network error: ' + e.message });
      });
  }

  loadGradesWhatIf(courseId) {
    const target = this.state.gradesWhatIfTarget;
    if (!target) return;
    const seq = ++this._gradesWhatIfSeq;
    this.setState({ gradesWhatIfLoading: true, gradesWhatIfError: null });
    fetch(`/api/courses/${courseId}/grades/whatif/?target=${encodeURIComponent(target)}`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesWhatIfSeq) return;
        if (!ok) { this.setState({ gradesWhatIfLoading: false, gradesWhatIfError: data.detail || 'Could not compute what-if.' }); return; }
        this.setState({ gradesWhatIfLoading: false, gradesWhatIf: data });
      })
      .catch(e => {
        if (seq !== this._gradesWhatIfSeq) return;
        this.setState({ gradesWhatIfLoading: false, gradesWhatIfError: 'Network error: ' + e.message });
      });
  }

  loadGradesSummary() {
    const seq = ++this._gradesSummarySeq;
    this.setState({ gradesSummaryLoading: true, gradesSummaryError: null });
    fetch('/api/grades/summary/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesSummarySeq) return;
        if (!ok) { this.setState({ gradesSummaryLoading: false, gradesSummaryError: data.detail || 'Could not load the semester summary.' }); return; }
        this.setState({ gradesSummaryLoading: false, gradesSummary: data });
      })
      .catch(e => {
        if (seq !== this._gradesSummarySeq) return;
        this.setState({ gradesSummaryLoading: false, gradesSummaryError: 'Network error: ' + e.message });
      });
  }

  checkAnswer(courseId) {
    const s = this.state;
    const userAnswer = (s.quizQuestion && s.quizQuestion.question_type === 'open_ended')
      ? (s.quizOpenAnswer || '').trim()
      : s.quizMcAnswer;
    if (!s.quizQuestion || !userAnswer) return;
    const seq = this._quizSeq;
    const q = s.quizQuestion;
    this.setState({ quizLoading: true, quizError: null, quizErrorSource: null });
    fetch(`/api/courses/${courseId}/quiz/record/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({
        lecture_id: q.lecture_id, chunk_id: q.chunk_id, topic: q.topic,
        question: q.question, correct_answer: q.correct_answer, user_answer: userAnswer
      })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._quizSeq) return;
        if (!ok) { this.setState({ quizLoading: false, quizError: data.detail || 'Could not record your answer.', quizErrorSource: 'record' }); return; }
        const nextCount = this.state.quizCorrectCount + (data.correct ? 1 : 0);
        if (this.state.quizStep + 1 < this.state.quizTargetCount) {
          this.setState({ quizLoading: false, quizCorrectCount: nextCount, quizStep: this.state.quizStep + 1 });
          this.loadQuestion(courseId);
        } else {
          this.setState({ quizLoading: false, quizCorrectCount: nextCount, quizStep: this.state.quizTargetCount });
        }
      })
      .catch(e => {
        if (seq !== this._quizSeq) return;
        this.setState({ quizLoading: false, quizError: 'Network error: ' + e.message, quizErrorSource: 'record' });
      });
  }

  openUpload(courseId) {
    const meta = this.state.courseMeta && this.state.courseMeta[courseId];
    const n = (meta && meta.notes_count) || 0;
    const suggested = 'lecture' + String(n + 1).padStart(2, '0');
    this.setState({
      uploadOpenFor: courseId, uploadLectureId: suggested, uploadDate: '',
      uploadFile: null, uploadLoading: false, uploadError: null, uploadConflict: null
    });
  }

  closeUpload() {
    this._uploadSeq++;
    this.setState({
      uploadOpenFor: null, uploadLectureId: '', uploadDate: '', uploadFile: null,
      uploadLoading: false, uploadError: null, uploadConflict: null
    });
  }

  submitUpload(overwrite) {
    const s = this.state;
    if (!s.uploadFile) { this.setState({ uploadError: 'Choose a file to upload.' }); return; }
    if (!s.uploadLectureId) { this.setState({ uploadError: 'Enter a lecture id.' }); return; }
    const seq = ++this._uploadSeq;
    const courseId = s.uploadOpenFor;
    this.setState({ uploadLoading: true, uploadError: null, uploadConflict: null });

    const body = new FormData();
    body.append('file', s.uploadFile);
    body.append('lecture_id', s.uploadLectureId);
    if (s.uploadDate) body.append('date', s.uploadDate);
    if (overwrite) body.append('overwrite', 'true');

    fetch(`/api/courses/${courseId}/notes/chunk/`, {
      method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: body
    })
      .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
      .then(({ ok, status, data }) => {
        if (seq !== this._uploadSeq) return;
        if (status === 409) { this.setState({ uploadLoading: false, uploadConflict: data }); return; }
        if (!ok) { this.setState({ uploadLoading: false, uploadError: data.detail || 'Could not process that file.' }); return; }
        this.closeUpload();
        this.loadDashboard();
      })
      .catch(e => {
        if (seq !== this._uploadSeq) return;
        this.setState({ uploadLoading: false, uploadError: 'Network error: ' + e.message });
      });
  }

  openAddGrade() {
    const s = this.state;
    const firstComponent = s.gradesBreakdown && s.gradesBreakdown.categories[0] ? s.gradesBreakdown.categories[0].component : '';
    this.setState({
      addGradeOpen: true, addGradeEditingId: null, addGradeComponent: firstComponent,
      addGradeTitle: '', addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '',
      addGradeLoading: false, addGradeError: null,
    });
  }

  openEditGrade(item) {
    this.setState({
      addGradeOpen: true, addGradeEditingId: item.id, addGradeComponent: item.component,
      addGradeTitle: item.title, addGradeScore: String(item.score), addGradeMaxPoints: String(item.max_points),
      addGradeDate: item.date || '', addGradeLoading: false, addGradeError: null,
    });
  }

  closeAddGrade() {
    this._addGradeSeq++;
    this.setState({
      addGradeOpen: false, addGradeEditingId: null, addGradeComponent: '', addGradeTitle: '',
      addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '', addGradeLoading: false, addGradeError: null,
    });
  }

  submitAddGrade() {
    const s = this.state;
    if (!s.addGradeComponent) { this.setState({ addGradeError: 'Choose a category.' }); return; }
    if (!s.addGradeTitle) { this.setState({ addGradeError: 'Enter a title.' }); return; }
    const score = parseFloat(s.addGradeScore);
    const maxPoints = parseFloat(s.addGradeMaxPoints);
    if (isNaN(score) || isNaN(maxPoints) || maxPoints <= 0) {
      this.setState({ addGradeError: 'Enter a valid score and max points.' });
      return;
    }

    const seq = ++this._addGradeSeq;
    const courseId = s.course;
    const body = { component: s.addGradeComponent, title: s.addGradeTitle, score: score, max_points: maxPoints, date: s.addGradeDate || null };
    this.setState({ addGradeLoading: true, addGradeError: null });

    const url = s.addGradeEditingId
      ? `/api/courses/${courseId}/grades/items/${s.addGradeEditingId}/`
      : `/api/courses/${courseId}/grades/items/`;
    const method = s.addGradeEditingId ? 'PATCH' : 'POST';

    fetch(url, {
      method: method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(body)
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._addGradeSeq) return;
        if (!ok) { this.setState({ addGradeLoading: false, addGradeError: data.detail || 'Could not save that grade.' }); return; }
        this.closeAddGrade();
        this.loadGrades(courseId);
      })
      .catch(e => {
        if (seq !== this._addGradeSeq) return;
        this.setState({ addGradeLoading: false, addGradeError: 'Network error: ' + e.message });
      });
  }

  openGradingSetup() {
    const s = this.state;
    const courseId = s.course;
    const seq = ++this._gradingSetupSeq;
    fetch(`/api/courses/${courseId}/grading/`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradingSetupSeq) return;
        if (!ok) { this.setState({ gradesError: data.detail || 'Could not load grading categories.' }); return; }

        const choices = data.category_choices || [];
        const checked = {};
        const fields = {};
        choices.forEach(name => {
          checked[name] = false;
          fields[name] = { weight_pct: '', total_items: '', drop_lowest: '' };
        });

        (data.grading || []).forEach(entry => {
          const target = choices.includes(entry.component)
            ? entry.component
            : this._guessCategoryForLegacyName(entry.component, choices);
          const wasChecked = checked[target];
          const prior = fields[target] || { weight_pct: '', total_items: '', drop_lowest: '' };
          checked[target] = true;
          if (!wasChecked) {
            fields[target] = {
              weight_pct: String(entry.weight_pct),
              total_items: entry.total_items != null ? String(entry.total_items) : '',
              drop_lowest: entry.drop_lowest ? String(entry.drop_lowest) : '',
            };
          } else {
            const priorWeight = parseFloat(prior.weight_pct);
            const newWeight = parseFloat(entry.weight_pct);
            const summedWeight = (isNaN(priorWeight) ? 0 : priorWeight) + (isNaN(newWeight) ? 0 : newWeight);

            const priorTotalItems = prior.total_items !== '' ? parseInt(prior.total_items, 10) : null;
            const newTotalItems = entry.total_items != null ? entry.total_items : null;
            let summedTotalItems;
            if (priorTotalItems != null && newTotalItems != null) {
              summedTotalItems = priorTotalItems + newTotalItems;
            } else if (priorTotalItems != null) {
              summedTotalItems = priorTotalItems;
            } else if (newTotalItems != null) {
              summedTotalItems = newTotalItems;
            } else {
              summedTotalItems = null;
            }

            fields[target] = {
              weight_pct: String(summedWeight),
              total_items: summedTotalItems != null ? String(summedTotalItems) : '',
              drop_lowest: prior.drop_lowest,
            };
          }
        });

        this.setState({
          gradingSetupOpen: true, gradingSetupCategoryChoices: choices,
          gradingSetupChecked: checked, gradingSetupFields: fields,
          gradingSetupError: null, gradingSetupLoading: false,
        });
      })
      .catch(e => {
        if (seq !== this._gradingSetupSeq) return;
        this.setState({ gradesError: 'Network error: ' + e.message });
      });
  }

  _guessCategoryForLegacyName(name, choices) {
    const lower = (name || '').toLowerCase();
    const synonyms = {
      Homework: ['homework', 'assignment', 'problem set', 'exercise'],
      Tests: ['test'],
      Quizzes: ['quiz'],
      Projects: ['project', 'presentation', 'capstone'],
      'Lab and Demo': ['lab', 'demo'],
      'Final Project': ['final project'],
      'Class Participation': ['class participation', 'participation'],
      Midterm: ['midterm'],
      Final: ['final'],
    };
    // Fixed precedence order, independent of `choices`' own ordering: more-specific
    // keywords (e.g. "final project") must be checked before the generic
    // "final" keyword.
    const precedence = [
      'Final Project',
      'Lab and Demo',
      'Class Participation',
      'Homework',
      'Tests',
      'Quizzes',
      'Projects',
      'Midterm',
      'Final',
    ];
    for (const category of precedence) {
      if (!choices.includes(category)) continue;
      const keywords = synonyms[category];
      if (keywords && keywords.some(k => lower.includes(k))) return category;
    }
    return choices.includes('Other') ? 'Other' : (choices[0] || 'Other');
  }

  closeGradingSetup() {
    this._gradingSetupSeq++;
    this.setState({
      gradingSetupOpen: false, gradingSetupCategoryChoices: [], gradingSetupChecked: {}, gradingSetupFields: {},
      gradingSetupError: null, gradingSetupLoading: false,
    });
  }

  toggleGradingSetupCategory(category) {
    this.setState({
      gradingSetupChecked: Object.assign({}, this.state.gradingSetupChecked, {
        [category]: !this.state.gradingSetupChecked[category],
      }),
    });
  }

  updateGradingSetupField(category, field, value) {
    const fields = Object.assign({}, this.state.gradingSetupFields, {
      [category]: Object.assign({}, this.state.gradingSetupFields[category], { [field]: value }),
    });
    this.setState({ gradingSetupFields: fields });
  }

  submitGradingSetup() {
    const s = this.state;
    const courseId = s.course;
    const grading = [];
    for (const category of s.gradingSetupCategoryChoices) {
      if (!s.gradingSetupChecked[category]) continue;
      const f = s.gradingSetupFields[category];
      const weight = parseFloat(f.weight_pct);
      if (isNaN(weight)) { this.setState({ gradingSetupError: `Enter a weight % for ${category}.` }); return; }
      const entry = { component: category, weight_pct: weight };
      if (f.total_items.trim()) {
        const totalItems = parseInt(f.total_items, 10);
        if (isNaN(totalItems) || totalItems < 1) { this.setState({ gradingSetupError: `Total items for ${category} must be a positive whole number.` }); return; }
        entry.total_items = totalItems;
      }
      if (f.drop_lowest.trim()) {
        const dropLowest = parseInt(f.drop_lowest, 10);
        if (isNaN(dropLowest) || dropLowest < 0) { this.setState({ gradingSetupError: `Drop-lowest for ${category} must be a non-negative whole number.` }); return; }
        entry.drop_lowest = dropLowest;
      }
      grading.push(entry);
    }

    const seq = ++this._gradingSetupSeq;
    this.setState({ gradingSetupLoading: true, gradingSetupError: null });
    fetch(`/api/courses/${courseId}/grading/`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ grading: grading })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradingSetupSeq) return;
        if (!ok) {
          const blocking = (data.errors || []).filter(e => !e.startsWith('WARNING'));
          this.setState({ gradingSetupLoading: false, gradingSetupError: blocking.join('; ') || data.detail || 'Could not save grading setup.' });
          return;
        }
        const warnings = data.warnings || [];
        this.closeGradingSetup();
        this.loadGrades(courseId);
        if (warnings.length) {
          this.setState({ gradesNotice: warnings.join(' ') });
        }
      })
      .catch(e => {
        if (seq !== this._gradingSetupSeq) return;
        this.setState({ gradingSetupLoading: false, gradingSetupError: 'Network error: ' + e.message });
      });
  }

  dismissGradesNotice() {
    this.setState({ gradesNotice: null });
  }

  deleteGradeItem(itemId) {
    if (!confirm('Delete this grade? This cannot be undone.')) return;
    const courseId = this.state.course;
    fetch(`/api/courses/${courseId}/grades/items/${itemId}/`, {
      method: 'DELETE', headers: { 'X-CSRFToken': getCookie('csrftoken') }
    })
      .then(r => {
        if (!r.ok) {
          return r.json().then(data => {
            this.setState({ gradesError: data.detail || 'Could not delete that grade.' });
          });
        }
        this.loadGrades(courseId);
      })
      .catch(e => {
        this.setState({ gradesError: 'Network error: ' + e.message });
      });
  }

  signOut() {
    fetch('/accounts/logout/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
      .then(() => { location.href = '/'; })
      .catch(() => { location.href = '/'; });
  }

  openSettings() {
    this.setState({
      settingsOpen: true,
      settingsName: this.state.currentUserName || '',
      settingsUsername: this.state.currentUsername || '',
      settingsNotifications: !!this.state.notificationsEnabled,
      settingsError: null,
    });
  }

  closeSettings() {
    this.setState({ settingsOpen: false, settingsSaving: false, settingsError: null });
  }

  onSettingsNameChange(e) {
    this.setState({ settingsName: e.target.value });
  }

  onSettingsUsernameChange(e) {
    this.setState({ settingsUsername: e.target.value });
  }

  onSettingsNotificationsChange(e) {
    this.setState({ settingsNotifications: !!e.target.checked });
  }

  connectCalendar() {
    window.location.assign('/accounts/calendar/connect/');
  }

  disconnectCalendar() {
    this.setState({ settingsSaving: true, settingsError: null });
    fetch('/accounts/calendar/disconnect/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      credentials: 'same-origin',
    }).then(response => {
      if (!response.ok && !response.redirected) throw new Error('Could not disconnect Google Calendar.');
      this.setState({ settingsSaving: false, calendarConnected: false });
    }).catch(error => this.setState({ settingsSaving: false, settingsError: error.message }));
  }

  saveSettings() {
    const name = (this.state.settingsName || '').trim();
    const username = (this.state.settingsUsername || '').trim();
    const notifications = !!this.state.settingsNotifications;
    if (!name) {
      this.setState({ settingsError: 'Name is required.' });
      return;
    }
    if (!username) {
      this.setState({ settingsError: 'Username is required.' });
      return;
    }

    const requestBrowserPermission = () => {
      if (!notifications || !('Notification' in window) || Notification.permission === 'granted') {
        return Promise.resolve(true);
      }
      if (Notification.permission === 'denied') {
        return Promise.resolve(false);
      }
      return Notification.requestPermission().then(permission => permission === 'granted');
    };

    this.setState({ settingsSaving: true, settingsError: null });
    requestBrowserPermission()
      .then(granted => {
        if (notifications && !granted) {
          throw new Error('Browser notification permission was not granted.');
        }
        return fetch('/api/profile/', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
          body: JSON.stringify({
            display_name: name,
            username: username,
            notifications_enabled: notifications,
          })
        });
      })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.setState({ settingsSaving: false, settingsError: data.detail || 'Could not save settings.' });
          return;
        }
        this.setState({
          settingsSaving: false,
          settingsOpen: false,
          currentUserEmail: data.email || this.state.currentUserEmail,
          currentUserName: data.display_name || name,
          currentUsername: data.username || username,
          notificationsEnabled: !!data.notifications_enabled,
        });
      })
      .catch(e => {
        this.setState({ settingsSaving: false, settingsError: e.message || 'Could not save settings.' });
      });
  }

  openAddClass() {
    this.setState({
      addClassOpen: true, addClassName: '', addClassId: '', addClassIdLocked: false,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  openAddClassForDraft(courseId, courseName) {
    this.setState({
      addClassOpen: true, addClassName: courseName, addClassId: courseId, addClassIdLocked: true,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  closeAddClass() {
    this._addClassSeq++;
    this.setState({
      addClassOpen: false, addClassName: '', addClassId: '', addClassIdLocked: false,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  submitAddClass() {
    const s = this.state;
    if (s.addClassIdLocked) {
      if (!s.addClassFile) { this.setState({ addClassError: 'Choose a syllabus file to upload.' }); return; }
    } else {
      if (!s.addClassName.trim() || !s.addClassId) { this.setState({ addClassError: 'Enter a class name.' }); return; }
      if (s.courseDrafts.some(d => d.course_id === s.addClassId)) {
        this.setState({ addClassError: 'A class with that name already exists as a draft — use its "Upload syllabus" button instead.' });
        return;
      }
    }
    const seq = ++this._addClassSeq;
    this.setState({ addClassLoading: true, addClassError: null });

    const onDone = ({ ok, status, data }) => {
      if (seq !== this._addClassSeq) return;
      if (status === 409) { this.setState({ addClassLoading: false, addClassError: data.detail || 'That class already exists.' }); return; }
      if (!ok) { this.setState({ addClassLoading: false, addClassError: data.detail || 'Could not create that class.' }); return; }
      this.closeAddClass();
      this.loadDashboard();
    };
    const onError = (e) => {
      if (seq !== this._addClassSeq) return;
      this.setState({ addClassLoading: false, addClassError: 'Network error: ' + e.message });
    };

    if (s.addClassFile) {
      const body = new FormData();
      body.append('file', s.addClassFile);
      body.append('course_name', s.addClassName);
      fetch(`/api/courses/${s.addClassId}/syllabus/extract/`, {
        method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: body
      })
        .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
        .then(onDone)
        .catch(onError);
      return;
    }

    fetch(`/api/courses/${s.addClassId}/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ course_name: s.addClassName })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
      .then(onDone)
      .catch(onError);
  }

  openUploadPicker() {
    this.setState({ uploadPickerOpen: true });
  }

  closeUploadPicker() {
    this.setState({ uploadPickerOpen: false });
  }

  startEditCourse(id, currentName) {
    this.setState({ editingCourseId: id, editingCourseName: currentName, editCourseError: null });
  }

  cancelEditCourse() {
    this._cancelingEdit = true;
    this.setState({ editingCourseId: null, editingCourseName: '', editCourseError: null });
  }

  onEditCourseKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      this.saveEditCourse();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.cancelEditCourse();
      if (e.target && e.target.blur) e.target.blur();
    }
  }

  onEditCourseBlur() {
    if (this._cancelingEdit) { this._cancelingEdit = false; return; }
    this.saveEditCourse();
  }

  saveEditCourse() {
    const id = this.state.editingCourseId;
    if (!id) return;
    const name = (this.state.editingCourseName || '').trim();
    if (!name) { this.cancelEditCourse(); return; }

    const currentName = (this.state.courseMeta && this.state.courseMeta[id] && this.state.courseMeta[id].course_name)
      || ((this.state.courseDrafts.find(d => d.course_id === id) || {}).course_name);
    if (name === currentName) { this.cancelEditCourse(); return; }

    const seq = ++this._renameSeq;
    this.setState({ editCourseError: null });
    fetch(`/api/courses/${id}/`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ course_name: name })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._renameSeq) return;
        if (!ok) { this.setState({ editCourseError: data.detail || 'Could not rename that class.' }); return; }
        this.setState({ editingCourseId: null, editingCourseName: '' });
        this.loadDashboard();
      })
      .catch(e => {
        if (seq !== this._renameSeq) return;
        this.setState({ editCourseError: 'Network error: ' + e.message });
      });
  }

  startDeleteCourse(id, name) {
    this.setState({ deleteCourseOpen: true, deleteCourseId: id, deleteCourseName: name, deleteCourseError: null, deleteCourseLoading: false });
  }

  closeDeleteCourse() {
    this._deleteCourseSeq++;
    this.setState({ deleteCourseOpen: false, deleteCourseId: null, deleteCourseName: '', deleteCourseError: null, deleteCourseLoading: false });
  }

  confirmDeleteCourse() {
    const id = this.state.deleteCourseId;
    if (!id) return;
    const seq = ++this._deleteCourseSeq;
    this.setState({ deleteCourseLoading: true, deleteCourseError: null });

    fetch(`/api/courses/${id}/`, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': getCookie('csrftoken'), 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: id })
    })
      .then(r => {
        if (seq !== this._deleteCourseSeq) return;
        if (r.ok) {
          const wasSelected = this.state.course === id;
          this.setState({ deleteCourseOpen: false, deleteCourseId: null, deleteCourseName: '', deleteCourseLoading: false });
          if (wasSelected) {
            this._quizSeq++;
            this._chatSeq++;
            const bounce = this.state.tab === 'quiz' || this.state.tab === 'progress' || this.state.tab === 'chat';
            this.setState(bounce ? { course: 'all', tab: 'dashboard' } : { course: 'all' });
          }
          this.loadDashboard();
          this.loadDashboardRecent(wasSelected ? 'all' : this.state.course);
          return;
        }
        return r.json().then(data => {
          if (seq !== this._deleteCourseSeq) return;
          this.setState({ deleteCourseLoading: false, deleteCourseError: data.detail || 'Could not delete that class.' });
        });
      })
      .catch(e => {
        if (seq !== this._deleteCourseSeq) return;
        this.setState({ deleteCourseLoading: false, deleteCourseError: 'Network error: ' + e.message });
      });
  }

  renderVals() {
    const s = this.state;
    const realCourseIds = Object.keys(s.courseMeta || {}).sort();
    const fallbackCourse = realCourseIds[0] || null;

    const deadlineCategoryInfo = {
      hw: { label: 'HW', bg: 'var(--color-accent-100)', text: 'var(--color-accent-800)', dot: 'var(--color-accent)' },
      project: { label: 'Project', bg: 'var(--color-accent-2-100)', text: 'var(--color-accent-2-800)', dot: 'var(--color-accent-2)' },
      test_quiz: { label: 'Test/Quiz', bg: '#efe9ff', text: '#5f43b2', dot: '#8f75e8' },
      class: { label: 'Class', bg: '#e6f3f5', text: '#24606a', dot: '#75bdc8' },
      other: { label: 'Other', bg: 'var(--color-neutral-200)', text: 'var(--color-text)', dot: 'var(--color-neutral-500)' },
      overdue: { label: 'Overdue', bg: '#fee2e2', text: '#991b1b', dot: '#dc2626' }
    };
    const deadlineInfo = (type) => deadlineCategoryInfo[normalizeDeadlineType(type)] || deadlineCategoryInfo.other;
    const isDeadlineOverdue = (d) => {
      const type = normalizeDeadlineType(d.type);
      return ['hw', 'project', 'test_quiz'].indexOf(type) >= 0 && !d.completed && d.date < isoDateLocal(new Date());
    };
    const deadlineEventStyle = (d, extra) => {
      const info = isDeadlineOverdue(d) ? deadlineCategoryInfo.overdue : deadlineInfo(d.type);
      const past = d.date < isoDateLocal(new Date()) && !isDeadlineOverdue(d);
      const borderColor = isDeadlineOverdue(d) ? info.dot : (d.course_color || info.dot);
      return 'background:' + info.bg + ';color:' + info.text + ';border-left-color:' + borderColor + ';opacity:' + (past ? '.52' : '1') + ';' + (extra || '');
    };
    const typeStyle = (type) => {
      const info = deadlineInfo(type);
      return 'font-size:11px;font-weight:600;padding:3px 9px;border-radius:99px;background:' + info.bg + ';color:' + info.text + ';flex:none';
    };
    // Mastery v2 status vocabulary (agent/services/mastery.py): not_started,
    // learning, needs_review, proficient, at_risk, exam_ready. "weak" /
    // "developing" / "strong" / "unassessed" are kept as aliases so any
    // stale, not-yet-rebuilt MasteryScore row (see mastery.py's docstring —
    // v1 rows are only replaced the next time rebuild_scores() runs) still
    // renders instead of showing as unstyled/blank.
    const statusColor = {
      not_started: 'var(--color-neutral-400)', unassessed: 'var(--color-neutral-400)',
      learning: 'var(--color-accent-700)', weak: 'var(--color-accent-700)',
      needs_review: 'var(--color-accent-700)', developing: 'var(--color-accent-700)',
      proficient: 'var(--color-accent-2-700)', strong: 'var(--color-accent-2-700)',
      exam_ready: 'var(--color-accent-2-700)',
      at_risk: '#dc2626',
    };
    const statusLabel = {
      not_started: 'Not started', unassessed: 'Not yet quizzed',
      learning: 'Learning', weak: 'Weak',
      needs_review: 'Needs review', developing: 'Developing',
      proficient: 'Proficient', strong: 'Strong',
      exam_ready: 'Exam ready',
      at_risk: 'At risk',
    };

    const courseMetaFor = (id) => (s.courseMeta && s.courseMeta[id]) || null;
    const progressTopicsRaw = (courseMetaFor(s.course) && courseMetaFor(s.course).topics) || [];
    const anyCourseHasNotes = realCourseIds.some(id => courseMetaFor(id) && courseMetaFor(id).notes_count > 0);
    const courseHasNotes = s.course === 'all'
      ? anyCourseHasNotes
      : !!(courseMetaFor(s.course) && courseMetaFor(s.course).notes_count > 0);
    const gradesOverallPct = s.gradesBreakdown && s.gradesBreakdown.overall_pct !== null
      ? Math.round(s.gradesBreakdown.overall_pct) + '%' : '—';
    const gradesOverallLetter = s.gradesBreakdown ? (s.gradesBreakdown.letter || 'No grade yet') : '';
    const gradesCategoriesGraded = s.gradesBreakdown
      ? s.gradesBreakdown.categories.filter(c => c.entered_count > 0).length : 0;
    const gradesCategoriesTotal = s.gradesBreakdown ? s.gradesBreakdown.categories.length : 0;
    const gradesCategoriesLabel = gradesCategoriesTotal > 0
      ? `${gradesCategoriesGraded} of ${gradesCategoriesTotal} categories graded` : 'No grading categories set up';
    const gradesItemsCount = s.gradesItems.length;
    const gradesBreakdownRows = (s.gradesBreakdown ? s.gradesBreakdown.categories : []).map(c => ({
      component: c.component,
      weightLabel: c.weight_pct + '%',
      avgLabel: c.avg_pct !== null ? Math.round(c.avg_pct) + '%' : 'No grades yet',
      countLabel: c.total_items ? `${c.entered_count} of ${c.total_items} entered` : `${c.entered_count} entered`,
      dropLabel: c.drop_lowest > 0 ? `Lowest ${c.drop_lowest} dropped` : null,
    }));
    const gradingSetupRows = s.gradingSetupCategoryChoices.map(category => ({
      category: category,
      checked: !!s.gradingSetupChecked[category],
      onToggle: () => this.toggleGradingSetupCategory(category),
      weight_pct: (s.gradingSetupFields[category] || {}).weight_pct || '',
      total_items: (s.gradingSetupFields[category] || {}).total_items || '',
      drop_lowest: (s.gradingSetupFields[category] || {}).drop_lowest || '',
      onWeightChange: (e) => this.updateGradingSetupField(category, 'weight_pct', e.target.value),
      onTotalItemsChange: (e) => this.updateGradingSetupField(category, 'total_items', e.target.value),
      onDropLowestChange: (e) => this.updateGradingSetupField(category, 'drop_lowest', e.target.value),
    }));
    const gradesHasGradingSetup = gradesCategoriesTotal > 0;
    const gradesShowContent = !s.gradesLoading && !s.gradesError;
    const gradesSummaryShowContent = !s.gradesSummaryLoading && !s.gradesSummaryError;
    const chipStyle = (selected) => 'padding:6px 12px;border-radius:99px;cursor:pointer;font-size:12.5px;font-family:var(--font-body);' +
      (selected ? 'border:1px solid var(--color-accent-700);background:var(--color-accent-100);font-weight:600' : 'border:1px solid var(--color-neutral-200);background:#fff');
    const addGradeComponentChips = (s.gradesBreakdown ? s.gradesBreakdown.categories : []).map(c => ({
      label: c.component,
      style: chipStyle(s.addGradeComponent === c.component),
      onClick: () => this.setState({ addGradeComponent: c.component }),
    }));
    const gradesItemRows = s.gradesItems.map(item => ({
      id: item.id, component: item.component, title: item.title,
      scoreLabel: item.score + '/' + item.max_points,
      dateLabel: item.date || '',
      onEdit: () => this.openEditGrade(item),
      onDelete: () => this.deleteGradeItem(item.id),
    }));
    const onGradesWhatIfTargetChange = (e) => {
      this.setState({ gradesWhatIfTarget: e.target.value });
    };
    const setGradesWhatIfToPassing = () => {
      const passing = (s.gradesBreakdown && s.gradesBreakdown.grade_scale && s.gradesBreakdown.grade_scale.passing_pct) || 60;
      this.setState({ gradesWhatIfTarget: String(passing) });
      this.loadGradesWhatIf(s.course);
    };
    const runGradesWhatIf = () => this.loadGradesWhatIf(s.course);

    const whatIf = s.gradesWhatIf;
    const gradesWhatIfSummary = (() => {
      if (!whatIf) return '';
      const n = whatIf.grade_needed;
      if (n.locked) {
        return n.achievable
          ? `Your grade is locked at ${n.ceiling_pct}% — you've already hit this target.`
          : `Your grade is locked at ${n.ceiling_pct}% — this target is no longer reachable.`;
      }
      if (!n.achievable) {
        return `Not achievable: you'd need to average ${n.p_needed}% on everything remaining (max possible is ${n.ceiling_pct}%).`;
      }
      if (n.p_needed <= 0) {
        return `Already guaranteed — you'd hit this target even scoring 0 on everything remaining.`;
      }
      return `You need to average ${n.p_needed}% on everything remaining to hit this target.`;
    })();
    const gradesWhatIfNotes = whatIf ? whatIf.grade_needed.notes : [];
    const gradesMissableRows = (whatIf ? whatIf.missable_by_category : [])
      .filter(m => !m.omitted_reason)
      .map(m => ({ label: `${m.component}: can miss ${m.missable} of ${m.remaining} remaining` }));
    const gradesMissableOmitted = (whatIf ? whatIf.missable_by_category : [])
      .filter(m => m.omitted_reason)
      .map(m => ({ label: `${m.component}: ${m.omitted_reason}` }));
    const gradesSummaryAveragePct = s.gradesSummary && s.gradesSummary.average_pct !== null
      ? Math.round(s.gradesSummary.average_pct) + '%' : 'No grades entered yet';
    const gradesSummaryExcludedLabel = (s.gradesSummary && s.gradesSummary.excluded_count > 0)
      ? `${s.gradesSummary.excluded_count} course(s) excluded — no grades entered yet` : '';
    const gradesSummaryRows = (s.gradesSummary ? s.gradesSummary.courses : []).map(c => ({
      courseId: c.course_id,
      name: c.course_name || (c.course_id || '').toUpperCase(),
      pctLabel: c.error ? 'Error' : (c.current_pct !== null && c.current_pct !== undefined ? Math.round(c.current_pct) + '%' : '—'),
      letterLabel: c.error ? c.error : (c.letter || 'No grade yet'),
      onClick: () => selectCourse(c.course_id),
    }));
    const onAddGradeTitleChange = (e) => this.setState({ addGradeTitle: e.target.value });
    const onAddGradeScoreChange = (e) => this.setState({ addGradeScore: e.target.value });
    const onAddGradeMaxPointsChange = (e) => this.setState({ addGradeMaxPoints: e.target.value });
    const onAddGradeDateChange = (e) => this.setState({ addGradeDate: e.target.value });
    const addGradeModalTitle = s.addGradeEditingId ? 'Edit grade' : 'Add grade';
    const addGradeSubmitLabel = s.addGradeEditingId ? 'Save' : 'Add';
    const courseMetaLoaded = s.courseMeta !== null;
    const courseIsDraft = s.course !== 'all' && s.courseDrafts.some(d => d.course_id === s.course);
    const draftName = courseIsDraft ? (s.courseDrafts.find(d => d.course_id === s.course) || {}).course_name : null;
    const courseDisplayName = s.course === 'all'
      ? 'your courses'
      : (courseMetaFor(s.course) && courseMetaFor(s.course).course_name) || draftName || s.course.toUpperCase();
    const scopeLabel = s.course === 'all' ? 'all courses' : s.course.toUpperCase();
    const emptyStateMessage = courseIsDraft
      ? "This class doesn't have a syllabus yet. Add one from the sidebar to start tracking it."
      : 'No notes uploaded yet for ' + courseDisplayName + ' — nothing to quiz or track until a lecture is added.';

    const dotColors = ['var(--color-accent)', 'var(--color-accent-2)'];
    const onEditCourseChange = (e) => this.setState({ editingCourseName: e.target.value });
    const chipEditFields = (id, rawName) => ({
      isEditing: s.editingCourseId === id,
      editValue: s.editingCourseId === id ? s.editingCourseName : rawName,
      onEditChange: onEditCourseChange,
      onEditKeyDown: (e) => this.onEditCourseKeyDown(e),
      onEditBlur: () => this.onEditCourseBlur(),
      onEditStart: (e) => { e.stopPropagation(); this.startEditCourse(id, rawName); },
      onDeleteStart: (e) => { e.stopPropagation(); this.startDeleteCourse(id, rawName); }
    });

    const courseChips = realCourseIds.map((id, i) => {
      const rawName = (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase();
      return Object.assign({
        id: id,
        label: rawName,
        chipStyle: this.courseChip(s.course === id),
        dotStyle: 'width:8px;height:8px;border-radius:99px;background:' + dotColors[i % dotColors.length] + ';flex:none',
        onClick: () => selectCourse(id)
      }, chipEditFields(id, rawName));
    }).concat(s.courseDrafts.map(d => Object.assign({
      id: d.course_id,
      label: d.course_name + ' · pending',
      chipStyle: this.courseChip(s.course === d.course_id),
      dotStyle: 'width:8px;height:8px;border-radius:99px;background:var(--color-neutral-400);flex:none',
      onClick: () => selectCourse(d.course_id)
    }, chipEditFields(d.course_id, d.course_name))));

    const onAddClassNameChange = (e) => {
      const name = e.target.value;
      if (s.addClassIdLocked) {
        this.setState({ addClassName: name });
      } else {
        this.setState({ addClassName: name, addClassId: slugify(name) });
      }
    };
    const onAddClassFileChange = (e) => this.setState({ addClassFile: e.target.files[0] || null, addClassError: null });
    const addClassModalTitle = s.addClassIdLocked ? ('Add syllabus — ' + s.addClassName) : 'Add a class';
    const addClassSubmitLabel = s.addClassIdLocked ? 'Upload syllabus' : 'Add class';
    const uploadPickerItems = realCourseIds.map(id => ({
      id: id,
      name: (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase(),
      onClick: () => { this.closeUploadPicker(); this.openUpload(id); }
    }));

    const goToQuiz = (courseId) => {
      this.setState({
        tab: 'quiz', course: courseId, quizStarted: false, quizStep: 0, quizCorrectCount: 0,
        quizSetupTopic: 'all', quizSeenQuestions: [],
        quizMcAnswer: null, quizOpenAnswer: '', quizQuestion: null, quizError: null
      });
    };

    const goToFlashcards = (courseId) => {
      const hasNotes = !!(courseMetaFor(courseId) && courseMetaFor(courseId).notes_count > 0);
      this.setState({
        tab: 'flashcards', course: courseId, flashcards: [], flashcardIndex: 0,
        flashcardFlipped: false, flashcardKnown: {}, flashcardStarred: {}, flashcardMode: 'study',
        flashcardHideMastered: false, flashcardCategory: 'all', flashcardSaving: false, flashcardsError: null
      });
      if (hasNotes || !courseMetaLoaded) this.loadFlashcards(courseId);
    };

    const setTab = (t) => {
      this._quizSeq++;
      this._chatSeq++;
      const pageName = window.ONTRACK_PAGE_NAME || 'dashboard';
      const studyTab = ['progress', 'quiz', 'flashcards', 'grades'].indexOf(t) >= 0;
      const majorPageMatches = (t === 'dashboard' && ['dashboard', 'courses', 'course-detail', 'materials'].indexOf(pageName) >= 0)
        || (t === 'deadlines' && pageName === 'calendar')
        || (t === 'chat' && pageName === 'cora')
        || (studyTab && pageName === 'study');
      if (!majorPageMatches && window.OnTrackNavigation) {
        const route = window.OnTrackNavigation.routeForTab(t);
        if (route) {
          const joiner = route.indexOf('?') >= 0 ? '&' : '?';
          const courseQuery = s.course && s.course !== 'all' ? joiner + 'course=' + encodeURIComponent(s.course) : '';
          window.location.assign(route + courseQuery);
          return;
        }
      }
      if (t === 'dashboard') {
        this.setState({ tab: t });
        this.loadDashboard();
        this.loadDashboardRecent(s.course);
        return;
      }
      if (t === 'deadlines') {
        this.setState({ tab: t, deadlineSyncError: null });
        this.loadAllDeadlines(s.course);
        return;
      }
      if (t === 'grades' && s.course === 'all') {
        this.setState({ tab: t });
        this.loadGradesSummary();
        return;
      }
      const targetCourse = s.course === 'all'
        ? (fallbackCourse || (s.courseDrafts[0] && s.courseDrafts[0].course_id) || null)
        : s.course;
      if (!targetCourse) return;
      if (t === 'quiz') {
        goToQuiz(targetCourse);
      } else if (t === 'flashcards') {
        goToFlashcards(targetCourse);
      } else if (t === 'chat') {
        this._chatAutoScroll = true;
        if (targetCourse !== s.course) {
          this.setState({
            tab: t, course: targetCourse, chatMessages: [], chatInput: '', chatError: null,
            chatSessionId: null, chatCopiedIndex: null, chatRetryQuestion: null,
            chatRetryRequestId: null, sourceDrawerOpen: false, sourceDrawerCitation: null,
            sourceDrawerData: null, sourceDrawerError: null
          });
        } else {
          this.setState({ tab: t, chatCopiedIndex: null });
        }
        this.loadChatSessions(targetCourse);
      } else if (t === 'progress') {
        this.setState({ tab: t, course: targetCourse });
        this.loadDashboard();
        this.loadDashboardRecent(targetCourse);
      } else if (t === 'grades') {
        this.setState({ tab: t, course: targetCourse, gradesWhatIfTarget: '' });
        this.loadGrades(targetCourse);
      } else {
        this.setState({ tab: t, course: targetCourse });
      }
    };

    const selectCourse = (courseId) => {
      this._quizSeq++;
      this._chatSeq++;
      if (courseId === 'all') {
        if (window.ONTRACK_PAGE_NAME === 'cora') {
          window.location.assign('/dashboard/');
          return;
        }
        if (window.ONTRACK_PAGE_NAME === 'study') {
          const nextTab = s.tab === 'quiz' || s.tab === 'flashcards' ? 'progress' : s.tab;
          this.setState({ course: 'all', tab: nextTab });
          this.loadDashboard();
          this.loadDashboardRecent('all');
          if (nextTab === 'grades') this.loadGradesSummary();
          return;
        }
        const bounce = s.tab === 'quiz' || s.tab === 'flashcards' || s.tab === 'progress' || s.tab === 'chat';
        this.setState(bounce ? { course: 'all', tab: 'dashboard' } : { course: 'all' });
        if (bounce) this.loadDashboard();
        this.loadDashboardRecent('all');
        if (s.tab === 'grades') { this.setState({ course: 'all' }); this.loadGradesSummary(); }
        if (s.tab === 'deadlines') { this.setState({ course: 'all', deadlinePopoverEvent: null }); this.loadAllDeadlines('all'); }
        return;
      }
      if (window.ONTRACK_PAGE_NAME === 'course-detail') {
        window.location.assign('/courses/' + encodeURIComponent(courseId) + '/');
        return;
      }
      if (window.ONTRACK_PAGE_NAME === 'materials') {
        window.location.assign('/courses/' + encodeURIComponent(courseId) + '/materials/');
        return;
      }
      if (s.tab === 'quiz') {
        goToQuiz(courseId);
      } else if (s.tab === 'flashcards') {
        goToFlashcards(courseId);
      } else if (s.tab === 'dashboard') {
        this.setState({ course: courseId });
        this.loadDashboardRecent(courseId);
      } else if (s.tab === 'chat') {
        if (courseId !== s.course) {
          this._chatAutoScroll = true;
          this.setState({
            course: courseId, chatMessages: [], chatInput: '', chatError: null,
            chatSessionId: null, chatCopiedIndex: null, chatRetryQuestion: null,
            chatRetryRequestId: null, sourceDrawerOpen: false, sourceDrawerCitation: null,
            sourceDrawerData: null, sourceDrawerError: null
          });
          this.loadChatSessions(courseId);
        }
      } else if (s.tab === 'progress') {
        this.setState({ course: courseId });
        this.loadDashboardRecent(courseId);
      } else if (s.tab === 'grades') {
        this.setState({ course: courseId, gradesWhatIfTarget: '' });
        this.loadGrades(courseId);
      } else if (s.tab === 'deadlines') {
        this.setState({ course: courseId, deadlineSyncError: null, deadlinePopoverEvent: null });
        this.loadAllDeadlines(courseId);
      } else {
        this.setState({ course: courseId });
      }
    };

    const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const dateParts = (isoDate) => {
      const bits = isoDate.split('-').map(Number);
      return { monthAbbrUpper: MONTH_LABELS[bits[1] - 1].toUpperCase(), monthLabel: MONTH_LABELS[bits[1] - 1], day: String(bits[2]) };
    };

    const DASHBOARD_DEADLINE_LIMIT = 6;
    const dashboardDeadlineSource = s.dashboardDeadlines.filter(d => s.course === 'all' || d.course_id === s.course);
    const deadlines = dashboardDeadlineSource.slice(0, DASHBOARD_DEADLINE_LIMIT).map(d => {
      const dp = dateParts(d.date);
      const key = d.id || (d.course_id + '|' + d.date + '|' + d.title);
      return {
        month: dp.monthAbbrUpper, day: dp.day, title: d.title,
        typeLabel: deadlineInfo(d.type).label,
        tagStyle: typeStyle(d.type),
        synced: !!d.synced,
        showCalendarSync: !!s.calendarConnected,
        addButtonLabel: s.dashboardSyncingKeys[key] ? 'Adding…' : 'Add to Calendar',
        onAddToCalendar: () => this.syncDashboardDeadline(d, key),
        examHref: (d.type === 'test_quiz' && d.course_id && d.id)
          ? '/courses/' + encodeURIComponent(d.course_id) + '/exams/' + encodeURIComponent(d.id) + '/'
          : ''
      };
    });
    const dashboardDeadlinesHiddenCount = Math.max(0, dashboardDeadlineSource.length - deadlines.length);
    const showDashboardDeadlinesLimit = dashboardDeadlinesHiddenCount > 0;
    const dashboardDeadlinesLimitText = showDashboardDeadlinesLimit
      ? ('Showing first ' + deadlines.length + ' of ' + dashboardDeadlineSource.length + '.')
      : '';
    const courseLabel = (id) => id ? id.toUpperCase() : 'General';
    const formatDateShort = (isoDate) => {
      if (!isoDate) return 'No date';
      const d = new Date(isoDate + 'T00:00:00');
      return MONTH_LABELS[d.getMonth()] + ' ' + d.getDate();
    };
    const formatDeadlineWhen = (d) => {
      const dateLabel = formatDateShort(d.date);
      if (!d.time) return dateLabel + ' · All day';
      return dateLabel + ' · ' + d.time.slice(0, 5) + (d.end_time ? '-' + d.end_time.slice(0, 5) : '');
    };
    const formatTimeDisplay = (value) => {
      const minutes = minutesFromTime(value);
      if (minutes === null) return '';
      const hour24 = Math.floor(minutes / 60);
      const minute = minutes % 60;
      const suffix = hour24 >= 12 ? 'PM' : 'AM';
      const hour = hour24 % 12 || 12;
      return hour + ':' + String(minute).padStart(2, '0') + ' ' + suffix;
    };
    const selectedDate = new Date((s.calendarSelectedDate || isoDateLocal(new Date())) + 'T00:00:00');
    const todayIso = isoDateLocal(new Date());
    const visibleDeadlineData = s.allDeadlines
      .filter(d => s.course === 'all' || d.course_id === s.course)
      .map(d => Object.assign({}, d, { type: normalizeDeadlineType(d.type), completed: !!d.completed }))
      .filter(d => s.deadlineCategoryFilters[normalizeDeadlineType(d.type)]);
    const enrichedDeadlines = visibleDeadlineData.map(d => {
      const start = minutesFromTime(d.time);
      const end = minutesFromTime(d.end_time) || (start !== null ? start + 60 : null);
      const timeRange = d.time ? (formatTimeDisplay(d.time) + (d.end_time ? ' - ' + formatTimeDisplay(d.end_time) : '')) : 'All day';
      const meta = courseLabel(d.course_id) + ' · ' + timeRange;
      return Object.assign({}, d, {
        calendarUid: (d.id || d.key || (d.date + '|' + d.title + '|' + (d.time || 'all-day'))),
        startMinutes: start,
        endMinutes: end,
        meta: meta,
        timeRange: timeRange,
        dateLabel: formatDateShort(d.date),
        categoryLabel: deadlineInfo(d.type).label,
        courseLabel: courseLabel(d.course_id),
        onEdit: () => this.openEditDeadline(d),
        style: deadlineEventStyle(d, '')
      });
    });
    const deadlinesEmpty = !s.deadlinesLoading && !s.deadlinesError && enrichedDeadlines.length === 0;
    const deadlinesScopeText = s.course === 'all'
      ? 'Everything upcoming, across every course.'
      : 'Upcoming deadlines for ' + courseDisplayName + '.';
    const deadlinesEmptyText = s.course === 'all'
      ? 'Add one manually or import a syllabus deadline when you have course dates.'
      : 'Add one manually or switch courses to review the full schedule.';
    const deadlinesEmptyTitle = s.course === 'all' ? 'No upcoming deadlines' : 'No deadlines here';
    const visibleDeadlinesCount = enrichedDeadlines.length + (enrichedDeadlines.length === 1 ? ' event' : ' events');
    const miniWeekdays = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
    const monthAnchor = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
    const miniStart = addDays(monthAnchor, -monthAnchor.getDay());
    const miniCalendarDays = Array.from({ length: 42 }, (_, i) => {
      const d = addDays(miniStart, i);
      const iso = isoDateLocal(d);
      let cls = 'mini-cal-day';
      if (d.getMonth() !== selectedDate.getMonth()) cls += ' muted';
      if (iso === todayIso) cls += ' today';
      if (iso === s.calendarSelectedDate) cls += ' selected';
      return { day: String(d.getDate()), className: cls, onClick: () => this.setState({ calendarSelectedDate: iso, deadlinePopoverEvent: null }) };
    });
    const miniCalendarTitle = MONTH_LABELS[selectedDate.getMonth()] + ' ' + selectedDate.getFullYear();
    let calendarMainTitle = s.calendarView === 'day'
      ? MONTH_LABELS[selectedDate.getMonth()] + ' ' + selectedDate.getDate() + ', ' + selectedDate.getFullYear()
      : miniCalendarTitle;
    const viewStart = s.calendarView === 'day' ? selectedDate : startOfWeek(selectedDate);
    const viewDays = Array.from({ length: s.calendarView === 'day' ? 1 : 7 }, (_, i) => addDays(viewStart, i));
    if (s.calendarView === 'week') {
      const viewEnd = viewDays[viewDays.length - 1];
      calendarMainTitle = viewStart.getMonth() === viewEnd.getMonth()
        ? MONTH_LABELS[viewStart.getMonth()] + ' ' + viewStart.getFullYear()
        : MONTH_LABELS[viewStart.getMonth()] + ' ' + viewStart.getDate() + ' - ' + MONTH_LABELS[viewEnd.getMonth()] + ' ' + viewEnd.getDate();
    }
    const periodStartIso = s.calendarView === 'month'
      ? isoDateLocal(monthAnchor)
      : isoDateLocal(viewStart);
    const periodEndIso = s.calendarView === 'month'
      ? isoDateLocal(new Date(selectedDate.getFullYear(), selectedDate.getMonth() + 1, 0))
      : isoDateLocal(viewDays[viewDays.length - 1]);
    const periodEvents = enrichedDeadlines.filter(d => d.date >= periodStartIso && d.date <= periodEndIso);
    const selectedDayEvents = enrichedDeadlines.filter(d => d.date === s.calendarSelectedDate);
    const periodAllDayCount = periodEvents.filter(d => d.startMinutes === null).length;
    const periodTimedCount = periodEvents.length - periodAllDayCount;
    const periodLabel = s.calendarView === 'month' ? 'This month' : s.calendarView === 'week' ? 'This week' : 'This day';
    const deadlineStats = [
      { value: String(periodEvents.length), label: periodLabel },
      { value: String(selectedDayEvents.length), label: 'Selected day' },
      { value: String(periodAllDayCount), label: 'All day' },
      { value: String(periodTimedCount), label: 'Timed' }
    ];
    const calendarDayHeaders = viewDays.map(d => {
      const iso = isoDateLocal(d);
      return {
        label: miniWeekdays[d.getDay()],
        day: String(d.getDate()),
        className: 'deadline-day-pill' + (iso === todayIso ? ' today' : '') + (iso === s.calendarSelectedDate ? ' selected' : '')
      };
    });
    const CALENDAR_START_HOUR = 8;
    const CALENDAR_END_HOUR = 19;
    const HOUR_HEIGHT = 88;
    const calendarStartMinutes = CALENDAR_START_HOUR * 60;
    const calendarEndMinutes = CALENDAR_END_HOUR * 60;
    const calendarHeight = (CALENDAR_END_HOUR - CALENDAR_START_HOUR) * HOUR_HEIGHT;
    const timeRows = Array.from({ length: CALENDAR_END_HOUR - CALENDAR_START_HOUR }, (_, i) => calendarStartMinutes + i * 60);
    const deadlineCalendarColumnsStyle = 'grid-template-columns:70px repeat(' + viewDays.length + ',minmax(' + (s.calendarView === 'day' ? '220px' : '120px') + ',1fr))';
    const deadlineTimeGridStyle = 'height:' + calendarHeight + 'px';
    const deadlineDayColumnsStyle = 'grid-template-columns:repeat(' + viewDays.length + ',minmax(' + (s.calendarView === 'day' ? '220px' : '120px') + ',1fr));height:' + calendarHeight + 'px';
    const calendarTimeRows = timeRows.map(min => ({
      label: ((min / 60) > 12 ? (min / 60 - 12) : (min / 60)) + ((min / 60) >= 12 ? ' pm' : ' am'),
      style: 'top:' + ((min - calendarStartMinutes) / 60 * HOUR_HEIGHT) + 'px'
    }));
    const assignCollisionColumns = (events) => {
      const sorted = events.slice().sort((a, b) => (a.startMinutes - b.startMinutes) || ((a.endMinutes || a.startMinutes + 60) - (b.endMinutes || b.startMinutes + 60)));
      const groups = [];
      sorted.forEach(event => {
        const end = event.endMinutes || event.startMinutes + 60;
        let group = groups.find(g => event.startMinutes < g.end && end > g.start);
        if (!group) {
          group = { start: event.startMinutes, end: end, events: [] };
          groups.push(group);
        }
        group.start = Math.min(group.start, event.startMinutes);
        group.end = Math.max(group.end, end);
        group.events.push(event);
      });
      return groups.reduce((acc, group) => {
        const columns = [];
        group.events.forEach(event => {
          const eventEnd = event.endMinutes || event.startMinutes + 60;
          let col = 0;
          while (columns[col] && event.startMinutes < columns[col]) col++;
          columns[col] = eventEnd;
          acc.push(Object.assign({}, event, { collisionIndex: col, collisionTotal: 0 }));
        });
        const total = Math.max(1, columns.length);
        return acc.map(event => group.events.some(g => g.calendarUid === event.calendarUid)
          ? Object.assign({}, event, { collisionTotal: total })
          : event);
      }, []);
    };
    const eventAriaLabel = (e) => e.title + ', ' + e.courseLabel + ', ' + e.dateLabel + ', ' + e.timeRange;
    const timedEventStyle = (e) => {
      const clampedStart = Math.max(calendarStartMinutes, e.startMinutes);
      const clampedEnd = Math.min(calendarEndMinutes, e.endMinutes || e.startMinutes + 60);
      const top = ((clampedStart - calendarStartMinutes) / 60) * HOUR_HEIGHT;
      const height = Math.max(34, ((clampedEnd - clampedStart) / 60) * HOUR_HEIGHT - 6);
      const total = e.collisionTotal || 1;
      const gap = 6;
      const widthPct = 100 / total;
      const leftPct = (e.collisionIndex || 0) * widthPct;
      const width = 'calc(' + widthPct + '% - ' + (gap + gap / total) + 'px)';
      const left = 'calc(' + leftPct + '% + ' + gap + 'px)';
      return deadlineEventStyle(e, 'top:' + top + 'px;height:' + height + 'px;left:' + left + ';width:' + width + ';');
    };
    const allDayColumnsRaw = viewDays.map(day => {
      const iso = isoDateLocal(day);
      return enrichedDeadlines
        .filter(e => e.date === iso && e.startMinutes === null)
        .map(e => Object.assign({}, e, {
          style: deadlineEventStyle(e, ''),
          ariaLabel: eventAriaLabel(e),
          onOpen: (ev) => this.openDeadlinePopover(e, ev)
        }));
    });
    const allDayColumns = allDayColumnsRaw.some(events => events.length)
      ? allDayColumnsRaw.map(events => ({ events: events }))
      : [];
    const calendarDayColumns = viewDays.map(day => {
      const iso = isoDateLocal(day);
      const dayEvents = assignCollisionColumns(enrichedDeadlines.filter(e => e.date === iso && e.startMinutes !== null && (e.endMinutes || e.startMinutes + 60) > calendarStartMinutes && e.startMinutes < calendarEndMinutes));
      const now = new Date(s.currentMinuteTick);
      const nowMinutes = now.getHours() * 60 + now.getMinutes();
      const showNow = iso === todayIso && nowMinutes >= calendarStartMinutes && nowMinutes <= calendarEndMinutes;
      return {
        showNow: showNow,
        nowStyle: 'top:' + (((nowMinutes - calendarStartMinutes) / 60) * HOUR_HEIGHT) + 'px',
        events: dayEvents.map(e => Object.assign({}, e, {
          className: 'deadline-event' + (s.deadlinePopoverEvent && s.deadlinePopoverEvent.calendarUid === e.calendarUid ? ' selected' : ''),
          style: timedEventStyle(e),
          ariaLabel: eventAriaLabel(e),
          onOpen: (ev) => this.openDeadlinePopover(e, ev)
        }))
      };
    });
    const visibleWeekEventCount = calendarDayColumns.reduce((sum, day) => sum + day.events.length, 0) + allDayColumnsRaw.reduce((sum, events) => sum + events.length, 0);
    const showEmptyWeekNote = !s.deadlinesLoading && !s.deadlinesError && visibleWeekEventCount === 0;
    const monthStart = addDays(monthAnchor, -monthAnchor.getDay());
    const monthCalendarCells = Array.from({ length: 42 }, (_, i) => {
      const d = addDays(monthStart, i);
      const iso = isoDateLocal(d);
      const dayEvents = enrichedDeadlines.filter(e => e.date === iso);
      const events = dayEvents.slice(0, 4).map(e => Object.assign({}, e, {
        style: deadlineEventStyle(e, ''),
        ariaLabel: eventAriaLabel(e),
        onOpen: (ev) => this.openDeadlinePopover(e, ev)
      }));
      return {
        day: String(d.getDate()),
        className: 'deadline-month-cell' + (d.getMonth() !== selectedDate.getMonth() ? ' muted' : ''),
        labelStyle: 'font-weight:900;color:' + (iso === todayIso ? 'var(--color-accent-700)' : 'inherit'),
        countLabel: dayEvents.length > 4 ? '+' + (dayEvents.length - 4) : '',
        events: events
      };
    });
    const fullWeekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const categoryCounts = { hw: 0, project: 0, test_quiz: 0, class: 0, other: 0 };
    s.allDeadlines.filter(d => s.course === 'all' || d.course_id === s.course).forEach(d => { categoryCounts[normalizeDeadlineType(d.type)]++; });
    const deadlineCategoryFilters = ['hw', 'project', 'test_quiz', 'class', 'other'].map(type => {
      const info = deadlineCategoryInfo[type];
      return {
        label: info.label,
        count: categoryCounts[type] || 0,
        dotStyle: 'background:' + info.dot + ';opacity:' + (s.deadlineCategoryFilters[type] ? '1' : '.25'),
        onToggle: () => this.setState({ deadlineCategoryFilters: Object.assign({}, s.deadlineCategoryFilters, { [type]: !s.deadlineCategoryFilters[type] }), deadlinePopoverEvent: null })
      };
    });

    const deadlineCourseOptions = realCourseIds.map(id => ({ id: id, name: (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase() }));
    const onDeadlineCourseChange = (e) => this.setState({ deadlineCourseId: e.target.value });
    const onDeadlineDateChange = (e) => this.setState({ deadlineDate: e.target.value });
    const onDeadlineTimeChange = (e) => this.setState({ deadlineTime: e.target.value });
    const onDeadlineEndTimeChange = (e) => this.setState({ deadlineEndTime: e.target.value });
    const onDeadlineTitleChange = (e) => this.setState({ deadlineTitle: e.target.value });
    const onDeadlineTypeChange = (e) => this.setState({ deadlineType: e.target.value });
    const onDeadlineCompletedChange = (e) => this.setState({ deadlineCompleted: !!e.target.checked });
    const onDeadlineEstimatedEffortChange = (e) => this.setState({ deadlineEstimatedEffort: e.target.value });
    const deadlineModalTitle = (s.deadlineEditingId || s.deadlineReplacingSyllabusKey) ? 'Edit deadline' : 'Add deadline';
    const deadlineSubmitLabel = (s.deadlineEditingId || s.deadlineReplacingSyllabusKey) ? 'Save' : 'Add deadline';
    const deadlineModalSubtitle = (s.deadlineEditingId || s.deadlineReplacingSyllabusKey)
      ? 'Update the date, category, course, or completion state.'
      : 'Create a course-specific or general deadline.';
    const deadlineTypeOptions = ['hw', 'project', 'test_quiz', 'class', 'other'].map(value => ({ value: value, label: deadlineCategoryInfo[value].label }));
    const popoverEvent = s.deadlinePopoverEvent;
    const popoverInfo = popoverEvent ? (deadlineInfo(popoverEvent.type) || deadlineCategoryInfo.other) : deadlineCategoryInfo.other;
    const deadlinePopoverOpen = !!popoverEvent;
    const deadlinePopoverTitle = popoverEvent ? popoverEvent.title : '';
    const deadlinePopoverCourse = popoverEvent ? popoverEvent.courseLabel : '';
    const deadlinePopoverCategory = popoverInfo.label;
    const deadlinePopoverDotStyle = 'background:' + popoverInfo.dot;
    const deadlinePopoverDate = popoverEvent ? popoverEvent.dateLabel : '';
    const deadlinePopoverTime = popoverEvent ? popoverEvent.timeRange : '';
    const deadlinePopoverCanDelete = !!(popoverEvent && ['manual', 'study_plan'].indexOf(popoverEvent.source) >= 0 && popoverEvent.id);
    const deadlinePopoverEffort = popoverEvent && popoverEvent.estimated_effort_minutes
      ? popoverEvent.estimated_effort_minutes + ' min estimated'
      : '';
    const weakTopicsForCourse = (id) => ((courseMetaFor(id) && courseMetaFor(id).weak_topics) || []).map(t => Object.assign({}, t, { course_id: id }));
    const rawWeakTopics = s.course === 'all'
      ? realCourseIds.map(weakTopicsForCourse).reduce((a, b) => a.concat(b), []).sort((a, b) => a.score - b.score)
      : weakTopicsForCourse(s.course);
    const weakTopics = rawWeakTopics.slice(0, s.course === 'all' ? 3 : 2).map(t => {
      const pct = Math.round(t.score * 100);
      return {
        topic: (s.course === 'all' ? t.course_id.toUpperCase() + ' — ' : '') + t.topic,
        pct: pct,
        barStyle: 'width:' + pct + '%;height:100%;border-radius:99px;background:var(--color-accent-700)'
      };
    });
    const practiceWeak = () => {
      this._quizSeq++;
      this._chatSeq++;
      const targetCourse = s.course === 'all'
        ? ((rawWeakTopics[0] && rawWeakTopics[0].course_id) || fallbackCourse || (s.courseDrafts[0] && s.courseDrafts[0].course_id) || null)
        : s.course;
      if (!targetCourse) return;
      goToQuiz(targetCourse);
    };
    const courseCardSummary = (meta) => {
      if (!meta || meta.error) return 'Loading…';
      const parts = [meta.topics_count + ' topics', meta.quizzed_count + ' quizzed'];
      if (meta.next_deadline) {
        const dp = dateParts(meta.next_deadline.date);
        parts.push(meta.next_deadline.title.toLowerCase() + ' ' + dp.monthLabel + ' ' + dp.day);
      }
      return parts.join(' · ');
    };
    const courseCardTags = (meta) => (meta && meta.weak_topics ? meta.weak_topics.slice(0, 2) : []).map(t => ({
      label: t.topic + ' — ' + (statusLabel[t.status] || t.status)
    }));
    const yourCoursesCards = realCourseIds
      .filter(id => s.course === 'all' || s.course === id)
      .map(id => {
        const meta = courseMetaFor(id);
        return {
          id: id, isDraft: false,
          kicker: id.toUpperCase(),
          name: (meta && meta.course_name) || id.toUpperCase(),
          summary: courseCardSummary(meta),
          tags: courseCardTags(meta),
          grading: (meta && meta.grading) || [],
          onUpload: () => this.openUpload(id),
          onOpenNotes: () => window.location.assign('/courses/' + encodeURIComponent(id) + '/materials/'),
          onOpenFlashcards: () => window.location.assign('/courses/' + encodeURIComponent(id) + '/study/flashcards/due/'),
          onOpenChat: () => window.location.assign('/cora/?course=' + encodeURIComponent(id))
        };
      })
      .concat(
        s.courseDrafts
          .filter(d => s.course === 'all' || s.course === d.course_id)
          .map(d => ({
            id: d.course_id, isDraft: true,
            kicker: d.course_id.toUpperCase(),
            name: d.course_name,
            onAddSyllabus: () => this.openAddClassForDraft(d.course_id, d.course_name)
          }))
      );
    const dashboardRecentActivity = s.dashboardRecentAttempts.map(a => ({
      topic: (s.course === 'all' ? a.course_id.toUpperCase() + ' · ' : '') + a.topic,
      question: a.question, correct: a.correct, incorrect: !a.correct,
      iconColor: a.correct ? 'var(--color-accent-2-700)' : 'var(--color-accent-700)'
    }));
    const dashboardScopeTag = s.course === 'all'
      ? (realCourseIds.length > 0 ? (realCourseIds.length + (realCourseIds.length === 1 ? ' course' : ' courses')) : 'No courses')
      : courseDisplayName;
    const progressMeta = courseMetaFor(s.course);
    const aggregateTopicsCount = realCourseIds.reduce((sum, id) => sum + (((courseMetaFor(id) || {}).topics_count) || 0), 0);
    const aggregateQuizzedCount = realCourseIds.reduce((sum, id) => sum + (((courseMetaFor(id) || {}).quizzed_count) || 0), 0);
    const aggregateQuizAttempts = realCourseIds.reduce((sum, id) => sum + (((courseMetaFor(id) || {}).quiz_attempts_count) || 0), 0);
    const aggregateQuizCorrect = realCourseIds.reduce((sum, id) => sum + (((courseMetaFor(id) || {}).quiz_correct_count) || 0), 0);
    const glanceTopicsCount = s.course === 'all' ? aggregateTopicsCount : ((progressMeta && progressMeta.topics_count) || 0);
    const glanceQuizzedCount = s.course === 'all' ? aggregateQuizzedCount : ((progressMeta && progressMeta.quizzed_count) || 0);
    const glanceQuizAttempts = s.course === 'all' ? aggregateQuizAttempts : ((progressMeta && progressMeta.quiz_attempts_count) || 0);
    const glanceQuizCorrect = s.course === 'all' ? aggregateQuizCorrect : ((progressMeta && progressMeta.quiz_correct_count) || 0);
    const syllabusCoveredPct = glanceTopicsCount > 0
      ? Math.round(100 * glanceQuizzedCount / glanceTopicsCount) + '%'
      : '—';
    const syllabusCoveredLabel = courseMetaLoaded
      ? (glanceQuizzedCount + ' of ' + glanceTopicsCount + ' topics quizzed')
      : 'Loading...';
    const streakLabel = s.dashboardStreak + (s.dashboardStreak === 1 ? ' day' : ' days');
    const streakSubLabel = s.dashboardStreak > 0 ? 'Keep it going' : 'Start today';
    const quizAccuracyPct = glanceQuizAttempts > 0
      ? Math.round(100 * glanceQuizCorrect / glanceQuizAttempts) + '%'
      : '—';
    const quizAccuracyLabel = glanceQuizAttempts > 0
      ? (glanceQuizCorrect + ' of ' + glanceQuizAttempts + ' answers correct')
      : 'No attempts yet';
    const retryDashboard = () => this.loadDashboard();
    const retryDashboardRecent = () => this.loadDashboardRecent(s.course);

    const uploadConflictPreview = (s.uploadConflict && s.uploadConflict.existing_preview) || null;
    const uploadConflictTopicsText = (uploadConflictPreview && uploadConflictPreview.topics || []).join(', ');
    const onUploadFileChange = (e) => this.setState({ uploadFile: e.target.files[0] || null, uploadError: null });
    const onUploadLectureIdChange = (e) => this.setState({ uploadLectureId: e.target.value });
    const onUploadDateChange = (e) => this.setState({ uploadDate: e.target.value });

    const allTopics = progressTopicsRaw.map(function (t) {
      var pct = t.score ? Math.round(t.score * 100) : 6;
      var color = t.score ? (statusColor[t.status] || 'var(--color-neutral-400)') : 'var(--color-neutral-300)';
      return {
        topic: t.topic,
        reason: t.reason || '',
        statusLabel: statusLabel[t.status] || t.status,
        statusStyle: 'font-size:12px;font-weight:600;color:' + color,
        barStyle: 'width:' + pct + '%;height:100%;border-radius:99px;background:' + color
      };
    });

    const mcOptionStyle = (selected) => 'width:100%;text-align:left;padding:13px 15px;border-radius:var(--radius-lg);cursor:pointer;font-size:14px;font-family:var(--font-body);' +
      (selected ? 'border:1px solid var(--color-accent-700);background:var(--color-accent-100);font-weight:600' : 'border:1px solid var(--color-neutral-200);background:#fff');
    const mcOptions = (s.quizQuestion ? s.quizQuestion.choices : []).map(label => ({
      label: label,
      onClick: () => this.setState({ quizMcAnswer: label }),
      style: mcOptionStyle(s.quizMcAnswer === label)
    }));
    const quizTypeOptionStyle = (selected) => 'width:100%;text-align:left;padding:14px 15px;border-radius:var(--radius-lg);cursor:pointer;font-size:14px;font-family:var(--font-body);font-weight:800;' +
      (selected ? 'border:2px solid var(--color-accent-700);background:var(--color-accent-100);color:var(--color-accent-800)' : 'border:1px solid var(--color-neutral-200);background:#fff;color:var(--color-text)');
    const quizTypeOptions = [
      { value: 'multiple_choice', label: 'Multiple choice' },
      { value: 'open_ended', label: 'Open ended' },
      { value: 'true_false', label: 'True/False' },
      { value: 'mixed', label: 'All of the above' }
    ].map(opt => ({
      label: opt.label,
      onClick: () => this.setState({ quizSetupType: opt.value }),
      style: quizTypeOptionStyle(s.quizSetupType === opt.value)
    }));
    const quizTopicOptions = [{ value: 'all', label: 'Whole course' }].concat(
      progressTopicsRaw.map(t => ({ value: t.topic, label: t.topic }))
    );
    const quizTopicLabel = s.quizQuestion ? s.quizQuestion.topic : (s.quizError ? '—' : 'Loading…');
    const assessmentComplete = s.quizStep >= s.quizTargetCount;
    const showQuizQuestion = !s.quizLoading && !s.quizError && !!s.quizQuestion && !assessmentComplete;
    const showQuizSetup = !s.quizStarted && !s.quizLoading;
    const showQuizOpenEnded = !!(s.quizQuestion && s.quizQuestion.question_type === 'open_ended');
    const showQuizChoices = !!(s.quizQuestion && s.quizQuestion.question_type !== 'open_ended');
    const quizProgressLabel = assessmentComplete ? 'Complete' : 'Question ' + (s.quizStep + 1) + ' of ' + s.quizTargetCount;
    const sourceNames = Array.from(new Set(s.flashcards.map(card => this.flashcardSourceName(card))));
    const flashcardCategoryOptions = [{ value: 'all', label: 'All Categories' }].concat(sourceNames.map(name => ({ value: name, label: name })));
    const visibleFlashcardIndices = this.flashcardVisibleIndices();
    const currentFlashcardIndex = visibleFlashcardIndices.indexOf(s.flashcardIndex) >= 0
      ? s.flashcardIndex
      : (visibleFlashcardIndices.length ? visibleFlashcardIndices[0] : s.flashcardIndex);
    const currentFlashcard = s.flashcards[currentFlashcardIndex] || null;
    const visiblePosition = visibleFlashcardIndices.indexOf(currentFlashcardIndex);
    const showFlashcard = !s.flashcardsLoading && !s.flashcardsError && s.flashcards.length > 0;
    const flashcardAllVisibleMastered = s.flashcards.length > 0 && visibleFlashcardIndices.length === 0;
    const masteredCount = s.flashcards.filter(card => card.status === 'mastered').length;
    const studyingCount = s.flashcards.filter(card => card.status === 'in_progress').length;
    const notStartedCount = Math.max(0, s.flashcards.length - masteredCount - studyingCount);
    const starredCount = s.flashcards.filter(card => card.starred).length;
    const flashcardIsStarred = !!(currentFlashcard && currentFlashcard.starred);
    const flashcardProgressPct = s.flashcards.length ? Math.round(((s.flashcardIndex + 1) / s.flashcards.length) * 100) : 0;
    const flashcardFrontIsTerm = s.flashcardReverse ? s.flashcardFlipped : !s.flashcardFlipped;
    const flashcardVisibleText = currentFlashcard
      ? cleanStudyText(flashcardFrontIsTerm ? currentFlashcard.term : currentFlashcard.definition)
      : '';
    const statusLabelFor = (status) => status === 'mastered' ? 'Mastered' : status === 'in_progress' ? 'In Progress' : 'Not Started';
    const statusStyleFor = (status) => 'font-size:11.5px;font-weight:800;color:' +
      (status === 'mastered' ? 'var(--color-accent-2-700)' : status === 'in_progress' ? 'var(--color-accent-700)' : 'var(--color-neutral-600)');
    const flashcardAllRows = s.flashcards.map((card, i) => ({
      term: cleanStudyText(card.term),
      definition: cleanStudyText(card.definition),
      statusLabel: statusLabelFor(card.status),
      statusStyle: statusStyleFor(card.status),
      starFill: card.starred ? 'currentColor' : 'none',
      onMaster: () => this.saveFlashcardProgress(i, { status: 'mastered' }, false),
      onProgress: () => this.saveFlashcardProgress(i, { status: 'in_progress' }, false),
      onReset: () => this.saveFlashcardProgress(i, { status: 'not_started' }, false),
      onToggleStar: () => this.saveFlashcardProgress(i, { starred: !card.starred }, false)
    }));
    const flashcardSourceLabel = currentFlashcard ? this.flashcardSourceName(currentFlashcard) : '';
    const flashcardStats = [
      { label: 'Total Cards', value: s.flashcards.length, iconStyle: 'background:var(--color-accent-2-200)', isTotal: true },
      { label: 'Mastered', value: masteredCount, iconStyle: 'background:var(--color-accent-2-300)', isMastered: true },
      { label: 'In Progress', value: studyingCount, iconStyle: 'background:var(--color-accent-200)', isProgress: true },
      { label: 'Not Started', value: notStartedCount, iconStyle: 'background:var(--color-neutral-200)', isNotStarted: true },
    ];
    const visibleCount = visibleFlashcardIndices.length;
    const visibleProgressNumber = visiblePosition >= 0 ? visiblePosition + 1 : 0;
    const visibleProgressPct = visibleCount ? Math.round((visibleProgressNumber / visibleCount) * 100) : 0;
    const flashcardFooterCountLabel = visibleCount ? ('Card ' + visibleProgressNumber + ' of ' + visibleCount) : 'No visible cards';
    const flashcardVisibleProgressLabel = visibleProgressNumber + '/' + visibleCount;
    const flashcardVisibleProgressBarStyle = 'width:' + visibleProgressPct + '%;height:100%;background:var(--color-accent);border-radius:999px';
    const flashcardRevealHint = s.flashcardFlipped ? 'Click to show prompt' : 'Click to reveal answer';
    const retryQuiz = () => {
      if (s.quizErrorSource === 'record') {
        this.checkAnswer(s.course);
      } else {
        this.loadQuestion(s.course);
      }
    };
    const onQuizSetupCountChange = (e) => {
      const value = e.target.value;
      if (value === '') {
        this.setState({ quizSetupCount: '' });
        return;
      }
      const parsed = parseInt(value, 10);
      if (isNaN(parsed)) return;
      this.setState({ quizSetupCount: String(Math.max(1, Math.min(15, parsed))) });
    };
    const onQuizOpenAnswerChange = (e) => this.setState({ quizOpenAnswer: e.target.value });
    const onQuizSetupTopicChange = (e) => this.setState({ quizSetupTopic: e.target.value, quizSeenQuestions: [] });
    const retryFlashcards = () => this.loadFlashcards(s.course);
    const onFlashcardCategoryChange = (e) => this.setState({ flashcardCategory: e.target.value, flashcardIndex: 0, flashcardFlipped: false });

    const quizDots = Array.from({ length: s.quizTargetCount }).map((_, i) => ({
      style: 'height:5px;flex:1;border-radius:99px;background:' + (i <= s.quizStep ? 'var(--color-accent-700)' : 'var(--color-neutral-200)')
    }));

    const msgStyle = (from) => from === 'user'
      ? { display: 'flex', justifyContent: 'flex-end' }
      : { display: 'flex', justifyContent: 'flex-start', alignItems: 'flex-start', gap: '10px' };
    const wrapStyle = (from) => 'display:flex;flex-direction:column;max-width:72%;' +
      (from === 'user' ? 'align-items:flex-end' : 'align-items:flex-start');
    const bubbleStyle = (from) => from === 'user'
      ? 'background:var(--color-accent);color:#fff;padding:11px 15px;border-radius:var(--radius-lg);font-size:14px;line-height:1.45'
      : 'background:var(--color-neutral-100);padding:11px 15px;border-radius:var(--radius-lg);font-size:14px;line-height:1.45';

    const hasSources = (m) => m.from === 'assistant' && !!(m.grounded && m.sources && m.sources.length);
    const formatPendingDeadlineDetails = (deadline) => {
      if (!deadline) return [];
      const info = deadlineCategoryInfo[normalizeDeadlineType(deadline.type)] || deadlineCategoryInfo.other;
      const courseMeta = deadline.course_id ? courseMetaFor(deadline.course_id) : null;
      const course = courseMeta ? courseMeta.name : (deadline.course_id ? deadline.course_id.toUpperCase() : 'General');
      const time = deadline.time ? (deadline.time + (deadline.end_time ? ('-' + deadline.end_time) : '')) : 'All day';
      return [
        { label: 'Course', value: course },
        { label: 'Type', value: info.label },
        { label: 'Date', value: deadline.date || 'No date' },
        { label: 'Time', value: time },
      ];
    };
    const formatPendingDeadlinesDetails = (deadlines) => {
      if (!deadlines.length) return [];
      if (deadlines.length === 1) return formatPendingDeadlineDetails(deadlines[0]);
      const first = deadlines[0] || {};
      const info = deadlineCategoryInfo[normalizeDeadlineType(first.type)] || deadlineCategoryInfo.other;
      const courseMeta = first.course_id ? courseMetaFor(first.course_id) : null;
      const course = courseMeta ? courseMeta.name : (first.course_id ? first.course_id.toUpperCase() : 'General');
      const dates = deadlines.map(d => d.date).filter(Boolean).sort();
      const dateLabel = dates.length > 6
        ? (dates[0] + ' to ' + dates[dates.length - 1])
        : dates.join(', ');
      const times = Array.from(new Set(deadlines.map(d => d.time ? (d.time + (d.end_time ? ('-' + d.end_time) : '')) : 'All day')));
      return [
        { label: 'Course', value: course },
        { label: 'Type', value: info.label },
        { label: 'Meetings', value: String(deadlines.length) },
        { label: dates.length > 6 ? 'Range' : 'Dates', value: dateLabel || 'No dates' },
        { label: 'Time', value: times.join(', ') || 'All day' },
      ];
    };
    const chatMessages = s.chatMessages.map((m, index) => {
      const pendingDeadlines = (m.pendingDeadlines && m.pendingDeadlines.length)
        ? m.pendingDeadlines
        : (m.pendingDeadline ? [m.pendingDeadline] : []);
      return {
      blocks: parseMarkdownBlocks(m.text), rowStyle: msgStyle(m.from), wrapStyle: wrapStyle(m.from), bubbleStyle: bubbleStyle(m.from),
      isAssistant: m.from === 'assistant',
      copyLabel: s.chatCopiedIndex === index ? 'Copied' : 'Copy',
      copyTitle: s.chatCopiedIndex === index ? 'Copied message' : 'Copy message',
      onCopy: () => this.copyChatMessage(m.text, index),
      hasSources: hasSources(m),
      notGroundedText: !hasSources(m) && m.from === 'assistant' ? 'Not grounded in your course material' : '',
      hasPendingDeadline: pendingDeadlines.length > 0,
      pendingDraftLabel: pendingDeadlines.length > 1 ? 'Schedule draft' : 'Deadline draft',
      pendingTitle: pendingDeadlines.length > 1 ? (pendingDeadlines.length + ' class meetings') : (pendingDeadlines[0] ? pendingDeadlines[0].title : ''),
      pendingDetails: formatPendingDeadlinesDetails(pendingDeadlines),
      pendingAddLabel: pendingDeadlines.length > 1 ? 'Add events' : 'Add deadline',
      canEditPending: pendingDeadlines.length === 1,
      onConfirmPending: () => this.confirmPendingDeadline(pendingDeadlines, index),
      onEditPending: () => this.prefillDeadlineModal(pendingDeadlines[0]),
      onCancelPending: () => this.dismissPendingDeadline(index),
      sourceItems: hasSources(m)
        ? m.sources.map(src => {
            if (src && typeof src === 'object') {
              return {
                text: src.title || src.material_id || 'Course source',
                kindLabel: src.material_type === 'web' ? 'Approved web' : 'Course material',
                isStructured: true, isLink: false, isPlain: false,
                onOpen: () => this.openSourcePreview(s.course, src)
              };
            }
            const text = String(src || '');
            const isLink = text.indexOf('http://') === 0 || text.indexOf('https://') === 0;
            return { text: text, isStructured: false, isLink: isLink, isPlain: !isLink, href: text };
          })
        : []
      };
    });
    const chatCourseMeta = courseMetaFor(s.course);
    const chatNotesCount = (chatCourseMeta && chatCourseMeta.notes_count) || 0;
    const chatReferencesCount = (chatCourseMeta && chatCourseMeta.references_count) || 0;
    const chatGroundingText = 'Cora only grounds answers in this course\'s syllabus'
      + (chatNotesCount > 0 ? ' and uploaded notes' : '')
      + (chatReferencesCount > 0 ? ' and uploaded references' : '')
      + ', and, when available, cited web results from domains you\'ve approved.';
    const chatNotesCountLabel = chatNotesCount > 0
      ? (chatNotesCount + (chatNotesCount === 1 ? ' lecture uploaded' : ' lectures uploaded'))
      : 'No lecture notes uploaded yet';
    const onChatInputChange = (e) => this.setState({ chatInput: e.target.value });
    const submitChat = () => {
      const text = (s.chatInput || '').trim();
      if (!text || s.chatLoading || s.chatSending) return;
      this.sendChatMessage(s.course, text);
    };
    const onChatInputKeyDown = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitChat();
      }
    };
    const startNewChat = () => {
      this._chatSeq++;
      this._chatAutoScroll = true;
      this.setState({
        chatMessages: [], chatInput: '', chatError: null, chatSessionId: null,
        chatLoading: false, chatCopiedIndex: null, chatRetryQuestion: null,
        chatRetryRequestId: null, sourceDrawerOpen: false, sourceDrawerCitation: null,
        sourceDrawerData: null, sourceDrawerError: null
      });
    };
    const sessionItemStyle = (active) => 'padding:8px;border-radius:var(--radius-lg);cursor:pointer;font-size:12.5px;' +
      (active ? 'background:var(--color-neutral-200)' : '');
    const formatSessionTime = (iso) => {
      const d = new Date(iso);
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    };
    const chatSessionItems = s.chatSessions.map(sess => ({
      title: sess.title || 'New chat',
      timeLabel: formatSessionTime(sess.updated_at || sess.created_at),
      countLabel: sess.message_count + (sess.message_count === 1 ? ' message' : ' messages'),
      itemStyle: sessionItemStyle(sess.session_id === s.chatSessionId),
      onClick: () => this.openChatSession(s.course, sess.session_id),
      onRename: (event) => this.renameChatSession(s.course, sess.session_id, sess.title, event),
      onDelete: (event) => this.deleteChatSession(s.course, sess.session_id, sess.title, event)
    }));
    const chatSessionsEmpty = !s.chatSessionsLoading && !s.chatSessionsError && s.chatSessions.length === 0;
    const sourceDrawerSource = s.sourceDrawerData || {};
    const sourceDrawerKindLabel = s.sourceDrawerData
      ? (sourceDrawerSource.material_type === 'web' ? 'Approved web material' : 'Course material')
      : (s.sourceDrawerError ? 'Source unavailable' : 'Verifying source');
    const sourceDrawerMeta = [
      sourceDrawerSource.lecture_id ? ('Lecture ' + sourceDrawerSource.lecture_id) : '',
      sourceDrawerSource.chunk_id ? ('Chunk ' + sourceDrawerSource.chunk_id) : '',
      sourceDrawerSource.page ? ('Page ' + sourceDrawerSource.page) : ''
    ].filter(Boolean).join(' · ');
    const notificationItems = s.notifications.map(n => ({
      title: n.title,
      body: n.body,
      meta: (n.course_id || 'General').toUpperCase() + (n.due_date ? ' · Due ' + n.due_date : ''),
      style: 'display:block;width:100%;border:0;border-bottom:1px solid var(--color-neutral-200);background:' + (n.read ? '#fff' : 'var(--color-accent-100)') + ';text-align:left;padding:12px 16px;cursor:pointer;color:var(--color-text)',
      onRead: () => this.markNotificationsRead([n.id])
    }));

    const displayName = s.currentUserName || s.currentUserEmail || 'there';
    const greetingHour = new Date().getHours();
    const greetingPrefix = greetingHour < 12 ? 'Good morning' : greetingHour < 18 ? 'Good afternoon' : 'Good evening';

    return {
      currentUserEmail: s.currentUserEmail,
      currentUserName: displayName,
      currentUsername: s.currentUsername,
      userInitial: displayName ? displayName[0].toUpperCase() : '?',
      dashboardGreeting: greetingPrefix + ', ' + displayName,
      dashboardScopeTag: dashboardScopeTag,
      openSettings: () => this.openSettings(),
      closeSettings: () => this.closeSettings(),
      saveSettings: () => this.saveSettings(),
      onSettingsNameChange: (e) => this.onSettingsNameChange(e),
      onSettingsUsernameChange: (e) => this.onSettingsUsernameChange(e),
      onSettingsNotificationsChange: (e) => this.onSettingsNotificationsChange(e),
      connectCalendar: () => this.connectCalendar(),
      disconnectCalendar: () => this.disconnectCalendar(),
      settingsOpen: s.settingsOpen,
      settingsName: s.settingsName,
      settingsUsername: s.settingsUsername,
      settingsNotifications: s.settingsNotifications,
      settingsSaving: s.settingsSaving,
      settingsError: s.settingsError,
      calendarConnected: s.calendarConnected,
      notificationsOpen: s.notificationsOpen,
      notificationsUnreadCount: s.notificationsUnreadCount,
      notificationsLoading: s.notificationsLoading,
      notificationsEmpty: !s.notificationsLoading && s.notifications.length === 0,
      notificationItems: notificationItems,
      toggleNotifications: () => this.toggleNotifications(),
      markAllNotificationsRead: () => this.markNotificationsRead(null),
      isDashboard: s.tab === 'dashboard',
      isChat: s.tab === 'chat',
      isProgress: s.tab === 'progress',
      isQuiz: s.tab === 'quiz',
      isFlashcards: s.tab === 'flashcards',
      isGrades: s.tab === 'grades',
      isGradesAllCourses: s.tab === 'grades' && s.course === 'all',
      isDeadlines: s.tab === 'deadlines',
      navBtnStyleDashboard: this.navBtn(s.tab === 'dashboard'),
      navBtnStyleChat: this.navBtn(s.tab === 'chat'),
      navBtnStyleProgress: this.navBtn(s.tab === 'progress'),
      navBtnStyleQuiz: this.navBtn(s.tab === 'quiz'),
      navBtnStyleFlashcards: this.navBtn(s.tab === 'flashcards'),
      navBtnStyleGrades: this.navBtn(s.tab === 'grades'),
      navBtnStyleDeadlines: this.navBtn(s.tab === 'deadlines'),
      courseChipStyleAll: this.courseChip(s.course === 'all'),
      courseChips: courseChips,
      signOut: () => this.signOut(),
      openAddClass: () => this.openAddClass(),
      addClassOpen: s.addClassOpen,
      addClassName: s.addClassName,
      addClassId: s.addClassId,
      addClassIdLocked: s.addClassIdLocked,
      addClassModalTitle: addClassModalTitle,
      addClassSubmitLabel: addClassSubmitLabel,
      onAddClassNameChange: onAddClassNameChange,
      onAddClassFileChange: onAddClassFileChange,
      addClassError: s.addClassError,
      addClassLoading: s.addClassLoading,
      closeAddClass: () => this.closeAddClass(),
      submitAddClass: () => this.submitAddClass(),
      openUploadPicker: () => this.openUploadPicker(),
      openUploadForCurrentCourse: () => {
        const target = s.course !== 'all' ? s.course : fallbackCourse;
        if (target) this.openUpload(target);
      },
      closeUploadPicker: () => this.closeUploadPicker(),
      uploadPickerOpen: s.uploadPickerOpen,
      uploadPickerEmpty: realCourseIds.length === 0,
      uploadPickerItems: uploadPickerItems,
      editCourseError: s.editCourseError,
      deleteCourseOpen: s.deleteCourseOpen,
      deleteCourseName: s.deleteCourseName,
      deleteCourseLoading: s.deleteCourseLoading,
      deleteCourseError: s.deleteCourseError,
      closeDeleteCourse: () => this.closeDeleteCourse(),
      confirmDeleteCourse: () => this.confirmDeleteCourse(),
      selectAll: () => selectCourse('all'),
      goDashboard: () => setTab('dashboard'),
      goChat: () => setTab('chat'),
      goProgress: () => setTab('progress'),
      goQuiz: () => setTab('quiz'),
      goFlashcards: () => setTab('flashcards'),
      goGrades: () => setTab('grades'),
      goDeadlines: () => setTab('deadlines'),
      gradesLoading: s.gradesLoading, gradesError: s.gradesError,
      gradesNotice: s.gradesNotice, dismissGradesNotice: () => this.dismissGradesNotice(),
      gradesSummaryLoading: s.gradesSummaryLoading, gradesSummaryError: s.gradesSummaryError,
      gradesSummaryAveragePct: gradesSummaryAveragePct, gradesSummaryExcludedLabel: gradesSummaryExcludedLabel,
      gradesSummaryRows: gradesSummaryRows,
      retryGradesSummary: () => this.loadGradesSummary(),
      gradesOverallPct: gradesOverallPct, gradesOverallLetter: gradesOverallLetter,
      gradesCategoriesLabel: gradesCategoriesLabel, gradesItemsCount: gradesItemsCount,
      gradesBreakdownRows: gradesBreakdownRows, gradesHasGradingSetup: gradesHasGradingSetup,
      gradesShowContent: gradesShowContent,
      gradesSummaryShowContent: gradesSummaryShowContent,
      gradesItemRows: gradesItemRows,
      gradesWhatIfTarget: s.gradesWhatIfTarget, onGradesWhatIfTargetChange: onGradesWhatIfTargetChange,
      setGradesWhatIfToPassing: setGradesWhatIfToPassing, runGradesWhatIf: runGradesWhatIf,
      gradesWhatIfLoading: s.gradesWhatIfLoading, gradesWhatIfError: s.gradesWhatIfError,
      gradesWhatIfSummary: gradesWhatIfSummary, gradesWhatIfNotes: gradesWhatIfNotes,
      gradesMissableRows: gradesMissableRows, gradesMissableOmitted: gradesMissableOmitted,
      hasGradesWhatIf: !!whatIf,
      addGradeOpen: s.addGradeOpen, addGradeModalTitle: addGradeModalTitle,
      addGradeSubmitLabel: addGradeSubmitLabel, addGradeComponentChips: addGradeComponentChips,
      addGradeTitle: s.addGradeTitle, addGradeScore: s.addGradeScore, addGradeMaxPoints: s.addGradeMaxPoints,
      addGradeDate: s.addGradeDate, addGradeLoading: s.addGradeLoading, addGradeError: s.addGradeError,
      onAddGradeTitleChange: onAddGradeTitleChange, onAddGradeScoreChange: onAddGradeScoreChange,
      onAddGradeMaxPointsChange: onAddGradeMaxPointsChange, onAddGradeDateChange: onAddGradeDateChange,
      openAddGrade: () => this.openAddGrade(),
      closeAddGrade: () => this.closeAddGrade(),
      submitAddGrade: () => this.submitAddGrade(),
      gradingSetupOpen: s.gradingSetupOpen, gradingSetupRows: gradingSetupRows,
      gradingSetupLoading: s.gradingSetupLoading, gradingSetupError: s.gradingSetupError,
      openGradingSetup: () => this.openGradingSetup(),
      closeGradingSetup: () => this.closeGradingSetup(),
      submitGradingSetup: () => this.submitGradingSetup(),
      retryGrades: () => this.loadGrades(s.course),
      practiceWeak: practiceWeak,
      courseName: courseDisplayName,
      courseIdUpper: s.course === 'all' ? 'ALL COURSES' : s.course.toUpperCase(),
      scopeLabel: scopeLabel,
      courseHasNotes: courseHasNotes,
      showNoNotesEmptyState: courseMetaLoaded && !courseHasNotes,
      emptyStateMessage: emptyStateMessage,
      courseIsDraft: courseIsDraft,
      yourCoursesGridStyle: 'display:grid;grid-template-columns:' + (s.course === 'all' ? '1fr 1fr' : '1fr') + ';gap:var(--space-4);margin-bottom:var(--space-6)',
      yourCoursesCards: yourCoursesCards,
      deadlines: deadlines, showDashboardDeadlinesLimit: showDashboardDeadlinesLimit,
      dashboardDeadlinesLimitText: dashboardDeadlinesLimitText,
      weakTopics: weakTopics, allTopics: allTopics, recentAttempts: dashboardRecentActivity, mcOptions: mcOptions, quizDots: quizDots,
      miniCalendarTitle: miniCalendarTitle, miniWeekdays: miniWeekdays, miniCalendarDays: miniCalendarDays,
      fullWeekdays: fullWeekdays, deadlineStats: deadlineStats,
      calendarMainTitle: calendarMainTitle, calendarDayHeaders: calendarDayHeaders, calendarTimeRows: calendarTimeRows,
      deadlineCalendarColumnsStyle: deadlineCalendarColumnsStyle, deadlineTimeGridStyle: deadlineTimeGridStyle,
      deadlineDayColumnsStyle: deadlineDayColumnsStyle, calendarDayColumns: calendarDayColumns,
      allDayColumns: allDayColumns, showEmptyWeekNote: showEmptyWeekNote,
      monthCalendarCells: monthCalendarCells, deadlineCategoryFilters: deadlineCategoryFilters,
      visibleDeadlinesCount: visibleDeadlinesCount,
      showCalendarWeekOrDay: !s.deadlinesLoading && !s.deadlinesError && s.calendarView !== 'month',
      showCalendarMonth: !deadlinesEmpty && !s.deadlinesLoading && !s.deadlinesError && s.calendarView === 'month',
      calendarMonthClass: s.calendarView === 'month' ? 'active' : '',
      calendarWeekClass: s.calendarView === 'week' ? 'active' : '',
      calendarDayClass: s.calendarView === 'day' ? 'active' : '',
      setCalendarMonth: () => this.setState({ calendarView: 'month', deadlinePopoverEvent: null }),
      setCalendarWeek: () => this.setState({ calendarView: 'week', deadlinePopoverEvent: null }),
      setCalendarDay: () => this.setState({ calendarView: 'day', deadlinePopoverEvent: null }),
      goCalendarToday: () => this.setState({ calendarSelectedDate: isoDateLocal(new Date()), deadlinePopoverEvent: null }),
      previousCalendarPeriod: () => this.setState({ calendarSelectedDate: isoDateLocal(addDays(selectedDate, s.calendarView === 'month' ? -30 : s.calendarView === 'week' ? -7 : -1)), deadlinePopoverEvent: null }),
      nextCalendarPeriod: () => this.setState({ calendarSelectedDate: isoDateLocal(addDays(selectedDate, s.calendarView === 'month' ? 30 : s.calendarView === 'week' ? 7 : 1)), deadlinePopoverEvent: null }),
      deadlinesEmpty: deadlinesEmpty, showDeadlineEmptyCard: deadlinesEmpty && s.calendarView === 'month',
      deadlinesEmptyTitle: deadlinesEmptyTitle, deadlinesEmptyText: deadlinesEmptyText,
      deadlinesScopeText: deadlinesScopeText, deadlinesLoading: s.deadlinesLoading, deadlinesError: s.deadlinesError,
      showDeadlineSyncError: !!s.deadlineSyncError, deadlineSyncError: s.deadlineSyncError,
      openAddDeadline: () => this.openAddDeadline(),
      deadlinePopoverOpen: deadlinePopoverOpen, deadlinePopoverStyle: s.deadlinePopoverStyle,
      deadlinePopoverTitle: deadlinePopoverTitle, deadlinePopoverCourse: deadlinePopoverCourse,
      deadlinePopoverCategory: deadlinePopoverCategory, deadlinePopoverDotStyle: deadlinePopoverDotStyle,
      deadlinePopoverDate: deadlinePopoverDate, deadlinePopoverTime: deadlinePopoverTime,
      deadlinePopoverEffort: deadlinePopoverEffort,
      deadlinePopoverCanDelete: deadlinePopoverCanDelete,
      closeDeadlinePopover: () => this.closeDeadlinePopover(), editDeadlineFromPopover: () => this.editDeadlineFromPopover(),
      deleteDeadlineFromPopover: () => this.deleteDeadlineFromPopover(),
      deadlineModalOpen: s.deadlineModalOpen, deadlineModalTitle: deadlineModalTitle, deadlineSubmitLabel: deadlineSubmitLabel,
      deadlineModalSubtitle: deadlineModalSubtitle, deadlineTypeOptions: deadlineTypeOptions,
      deadlineCourseId: s.deadlineCourseId, deadlineCourseOptions: deadlineCourseOptions, onDeadlineCourseChange: onDeadlineCourseChange,
      deadlineDate: s.deadlineDate, onDeadlineDateChange: onDeadlineDateChange,
      deadlineTime: s.deadlineTime, onDeadlineTimeChange: onDeadlineTimeChange,
      deadlineEndTime: s.deadlineEndTime, onDeadlineEndTimeChange: onDeadlineEndTimeChange,
      deadlineTitle: s.deadlineTitle, onDeadlineTitleChange: onDeadlineTitleChange,
      deadlineType: s.deadlineType, onDeadlineTypeChange: onDeadlineTypeChange,
      deadlineCompleted: s.deadlineCompleted, onDeadlineCompletedChange: onDeadlineCompletedChange,
      deadlineEstimatedEffort: s.deadlineEstimatedEffort, onDeadlineEstimatedEffortChange: onDeadlineEstimatedEffortChange,
      deadlineModalLoading: s.deadlineModalLoading, deadlineModalError: s.deadlineModalError,
      closeDeadlineModal: () => this.closeDeadlineModal(), submitDeadlineModal: () => this.submitDeadlineModal(),
      deleteDeadlineOpen: s.deleteDeadlineOpen, deleteDeadlineTitle: s.deleteDeadlineTitle,
      deleteDeadlineLoading: s.deleteDeadlineLoading, deleteDeadlineError: s.deleteDeadlineError,
      closeDeleteDeadline: () => this.closeDeleteDeadline(), confirmDeleteDeadline: () => this.confirmDeleteDeadline(),
      goToDeadlinesTab: () => setTab('deadlines'),
      syllabusCoveredPct: syllabusCoveredPct, syllabusCoveredLabel: syllabusCoveredLabel,
      streakLabel: streakLabel, streakSubLabel: streakSubLabel,
      quizAccuracyPct: quizAccuracyPct, quizAccuracyLabel: quizAccuracyLabel,
      dashboardLoading: s.dashboardLoading,
      showDashboardError: !!s.dashboardError && !s.courseMeta,
      dashboardError: s.dashboardError,
      retryDashboard: retryDashboard,
      showDashboardSyncError: !!s.dashboardSyncError,
      dashboardSyncError: s.dashboardSyncError,
      showDashboardLoading: s.dashboardLoading && !s.courseMeta,
      dashboardRecentActivity: dashboardRecentActivity,
      dashboardRecentLoading: s.dashboardRecentLoading,
      dashboardRecentError: s.dashboardRecentError,
      retryDashboardRecent: retryDashboardRecent,
      uploadModalOpen: !!s.uploadOpenFor,
      uploadModalCourseUpper: s.uploadOpenFor ? s.uploadOpenFor.toUpperCase() : '',
      uploadLectureId: s.uploadLectureId,
      uploadDate: s.uploadDate,
      uploadLoading: s.uploadLoading,
      uploadError: s.uploadError,
      hasUploadConflict: !!s.uploadConflict,
      uploadConflictPreview: uploadConflictPreview,
      uploadConflictTopicsText: uploadConflictTopicsText,
      onUploadFileChange: onUploadFileChange,
      onUploadLectureIdChange: onUploadLectureIdChange,
      onUploadDateChange: onUploadDateChange,
      closeUpload: () => this.closeUpload(),
      cancelConflict: () => this.setState({ uploadConflict: null }),
      submitUpload: () => this.submitUpload(false),
      confirmOverwrite: () => this.submitUpload(true),
      quizPos: s.quizStep + 1,
      isQuizStep3: assessmentComplete,
      quizTargetCount: s.quizTargetCount,
      showQuizSetup: showQuizSetup,
      quizSetupCount: s.quizSetupCount,
      onQuizSetupCountChange: onQuizSetupCountChange,
      quizTypeOptions: quizTypeOptions,
      quizSetupTopic: s.quizSetupTopic,
      quizTopicOptions: quizTopicOptions,
      onQuizSetupTopicChange: onQuizSetupTopicChange,
      startQuiz: () => this.startQuiz(s.course),
      quizProgressLabel: quizProgressLabel,
      showFlashcard: showFlashcard,
      flashcardsLoading: s.flashcardsLoading,
      flashcardsError: s.flashcardsError,
      flashcardSaving: s.flashcardSaving,
      flashcardDeckSubtitle: s.flashcards.length
        ? (masteredCount + ' mastered · ' + studyingCount + ' in progress · ' + starredCount + ' starred')
        : 'Low-cost definition drills generated with Haiku.',
      flashcardStudyModeClass: 'flashcard-segment' + (s.flashcardMode === 'study' ? ' active' : ''),
      flashcardAllCardsClass: 'flashcard-segment' + (s.flashcardMode === 'all' ? ' active' : ''),
      flashcardIsStudyMode: s.flashcardMode === 'study',
      setFlashcardStudyMode: () => this.setState({ flashcardMode: 'study', flashcardFlipped: false }),
      setFlashcardAllCardsMode: () => this.setState({ flashcardMode: 'all', flashcardFlipped: false }),
      flashcardHideMastered: s.flashcardHideMastered,
      toggleFlashcardHideMastered: () => this.toggleFlashcardHideMastered(),
      flashcardCategory: s.flashcardCategory,
      flashcardCategoryOptions: flashcardCategoryOptions,
      onFlashcardCategoryChange: onFlashcardCategoryChange,
      flashcardAllVisibleMastered: flashcardAllVisibleMastered,
      flashcardCategoryLabel: flashcardSourceLabel,
      flashcardShowingTerm: flashcardFrontIsTerm,
      flashcardVisibleText: flashcardVisibleText,
      flashcardRevealHint: flashcardRevealHint,
      flashcardVisibleProgressLabel: flashcardVisibleProgressLabel,
      flashcardVisibleProgressBarStyle: flashcardVisibleProgressBarStyle,
      flashcardFooterCountLabel: flashcardFooterCountLabel,
      flashcardStats: flashcardStats,
      flashcardAllRows: flashcardAllRows,
      flashcardStarFill: flashcardIsStarred ? 'currentColor' : 'none',
      flipFlashcard: () => this.flipFlashcard(),
      nextFlashcard: () => this.nextFlashcard(s.course),
      previousFlashcard: () => this.previousFlashcard(),
      markFlashcardKnown: () => this.markFlashcardKnown(true),
      toggleFlashcardStar: (e) => { if (e && e.stopPropagation) e.stopPropagation(); this.toggleFlashcardStar(); },
      shuffleFlashcards: () => this.shuffleFlashcards(),
      resetFlashcardProgress: () => this.resetFlashcardProgress(),
      retryFlashcards: retryFlashcards,
      quizCorrectCount: s.quizCorrectCount,
      quizTopicLabel: quizTopicLabel,
      showQuizQuestion: showQuizQuestion,
      showQuizChoices: showQuizChoices,
      showQuizOpenEnded: showQuizOpenEnded,
      quizOpenAnswer: s.quizOpenAnswer,
      onQuizOpenAnswerChange: onQuizOpenAnswerChange,
      quizLoading: s.quizLoading,
      quizError: s.quizError,
      quizQuestionText: s.quizQuestion ? s.quizQuestion.question : '',
      checkAnswer: () => this.checkAnswer(s.course),
      retryQuiz: retryQuiz,
      chatMessages: chatMessages,
      chatIsEmpty: s.chatMessages.length === 0,
      chatInput: s.chatInput,
      chatBusy: s.chatLoading || s.chatSending,
      chatSending: s.chatSending,
      chatError: s.chatError,
      chatCanRetry: !!s.chatRetryQuestion && !s.chatSending,
      retryChat: () => this.retryChatMessage(s.course),
      chatGroundingText: chatGroundingText,
      chatNotesCountLabel: chatNotesCountLabel,
      handleChatScroll: this.handleChatScroll,
      onChatInputChange: onChatInputChange,
      onChatInputKeyDown: onChatInputKeyDown,
      submitChat: submitChat,
      startNewChat: startNewChat,
      chatSessionItems: chatSessionItems,
      chatSessionsLoading: s.chatSessionsLoading,
      chatSessionsError: s.chatSessionsError,
      chatSessionsEmpty: chatSessionsEmpty,
      sourceDrawerOpen: s.sourceDrawerOpen,
      sourceDrawerLoading: s.sourceDrawerLoading,
      sourceDrawerError: s.sourceDrawerError,
      sourceDrawerTitle: sourceDrawerSource.title || 'Source preview',
      sourceDrawerKindLabel: sourceDrawerKindLabel,
      sourceDrawerMeta: sourceDrawerMeta,
      sourceDrawerExcerpt: sourceDrawerSource.excerpt || '',
      sourceDrawerHasUrl: !!sourceDrawerSource.url,
      sourceDrawerUrl: sourceDrawerSource.url || '',
      closeSourcePreview: () => this.closeSourcePreview()
    };
  }
}

}

window.createOnTrackComponent = createOnTrackComponent;
