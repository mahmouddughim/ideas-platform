import { db } from './db.js';

export const AUDIENCES = {
  personal: '🔒 لنفسي',
  publish: '🌍 للنشر لاحقاً',
};

export const STATUSES = {
  draft: 'مسودة',
  developing: 'قيد التطوير',
  ready: 'جاهزة',
  published: 'منشورة',
  archived: 'مؤرشفة',
};

export const PROJECT_TYPES = [
  'تطبيق / برمجة',
  'مشروع تجاري',
  'محتوى / كتابة',
  'تعليم',
  'خدمة مجتمعية',
  'تصميم / فن',
  'شخصي / تطوير الذات',
  'أخرى',
];

export const GOALS = ['ربح مادي', 'حل مشكلة', 'تعلّم', 'متعة / هواية', 'أثر اجتماعي', 'بناء سمعة', 'أخرى'];

const DEFAULT_SECTIONS = [
  { id: 'sec-tech', name: 'تقنية', icon: '💻' },
  { id: 'sec-business', name: 'أعمال', icon: '💼' },
  { id: 'sec-content', name: 'محتوى', icon: '✍️' },
  { id: 'sec-life', name: 'حياة شخصية', icon: '🌱' },
];

// Keep at most this many previous versions per idea.
const MAX_VERSIONS = 50;

export const uid = (prefix = 'id') =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export const now = () => new Date().toISOString();

export async function loadSections() {
  let sections = await db.all('sections');
  if (!sections.length) {
    await db.putMany('sections', DEFAULT_SECTIONS);
    sections = DEFAULT_SECTIONS;
  }
  return sections.filter((s) => !s.deleted);
}

export async function saveSection(section) {
  const s = { ...section, id: section.id || uid('sec'), updatedAt: now() };
  await db.put('sections', s);
  return s;
}

export async function deleteSection(id) {
  const s = await db.get('sections', id);
  if (s) await db.put('sections', { ...s, deleted: true, updatedAt: now() });
}

export async function loadIdeas() {
  const ideas = await db.all('ideas');
  return ideas.filter((i) => !i.deleted).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export const getIdea = (id) => db.get('ideas', id);

export function newIdea(sectionId) {
  const t = now();
  return {
    id: uid('idea'),
    title: '',
    body: '',
    sectionId: sectionId || '',
    projectType: '',
    goal: '',
    audience: 'personal',
    status: 'draft',
    tags: [],
    createdAt: t,
    updatedAt: t,
    versions: [],
    analysis: null,
  };
}

// Saves an idea. When the title or text changes, the previous text goes into the
// version history so nothing written is lost. Edits within one writing session
// (SNAPSHOT_GAP) are grouped into a single version, since the editor autosaves.
const SNAPSHOT_GAP = 10 * 60 * 1000;

export async function saveIdea(idea) {
  const prev = await db.get('ideas', idea.id);
  const next = { ...idea, updatedAt: now() };
  const changed = prev && (prev.title !== idea.title || prev.body !== idea.body);
  const hadContent = prev && (prev.title || prev.body);
  const sinceSnapshot = Date.now() - new Date(prev?.lastSnapshotAt || 0).getTime();
  if (changed && hadContent && sinceSnapshot > SNAPSHOT_GAP) {
    next.versions = [
      { at: prev.updatedAt, title: prev.title, body: prev.body },
      ...(prev.versions || []),
    ].slice(0, MAX_VERSIONS);
    next.lastSnapshotAt = next.updatedAt;
  }
  await db.put('ideas', next);
  return next;
}

export async function deleteIdea(id) {
  const idea = await db.get('ideas', id);
  if (idea) await db.put('ideas', { ...idea, deleted: true, updatedAt: now() });
}

// Records the user's answer to one of Claude's questions.
export async function answerQuestion(ideaId, questionId, answer, note) {
  const idea = await db.get('ideas', ideaId);
  const q = idea?.analysis?.questions?.find((x) => x.id === questionId);
  if (!q) return idea;
  if (answer !== undefined) q.answer = answer;
  if (note !== undefined) q.note = note;
  q.answeredAt = now();
  idea.updatedAt = now();
  await db.put('ideas', idea);
  return idea;
}
