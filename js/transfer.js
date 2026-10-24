// Export / import of the whole library as one JSON file.
// The same format is used for manual backups and for exchanging ideas with
// Claude: Claude reads the export, adds an `analysis` to each idea and sends a
// file back, which is merged here without overwriting newer local edits.
// See docs/claude-format.md for the format.
import { db } from './db.js';
import { now } from './model.js';

export const FORMAT = 'ideas-platform';
export const FORMAT_VERSION = 1;

export async function buildExport({ onlyIds } = {}) {
  const [ideas, sections] = await Promise.all([db.all('ideas'), db.all('sections')]);
  return {
    format: FORMAT,
    version: FORMAT_VERSION,
    exportedAt: now(),
    sections,
    ideas: onlyIds ? ideas.filter((i) => onlyIds.includes(i.id)) : ideas,
  };
}

export function download(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const stamp = () => new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');

const newer = (a, b) => (a || '') > (b || '');

function mergeAnalysis(local, incoming) {
  if (!incoming) return local;
  if (!local || newer(incoming.at, local.at)) {
    // Keep answers already given locally for questions with the same id.
    const answered = new Map((local?.questions || []).map((q) => [q.id, q]));
    const questions = (incoming.questions || []).map((q) => {
      const mine = answered.get(q.id);
      return mine && newer(mine.answeredAt, q.answeredAt)
        ? { ...q, answer: mine.answer, note: mine.note, answeredAt: mine.answeredAt }
        : q;
    });
    return { ...incoming, questions };
  }
  // Local analysis is newer; still pick up answers that are newer in the file.
  const theirs = new Map((incoming.questions || []).map((q) => [q.id, q]));
  return {
    ...local,
    questions: (local.questions || []).map((q) => {
      const t = theirs.get(q.id);
      return t && newer(t.answeredAt, q.answeredAt) ? { ...q, answer: t.answer, note: t.note, answeredAt: t.answeredAt } : q;
    }),
  };
}

export async function importData(data) {
  if (!data || data.format !== FORMAT || !Array.isArray(data.ideas)) {
    throw new Error('الملف ليس بصيغة منصة الأفكار');
  }
  const stats = { added: 0, updated: 0, analyzed: 0 };

  for (const s of data.sections || []) {
    const mine = await db.get('sections', s.id);
    if (!mine || newer(s.updatedAt, mine.updatedAt)) await db.put('sections', s);
  }

  for (const inc of data.ideas) {
    if (!inc?.id) continue;
    const mine = await db.get('ideas', inc.id);
    if (!mine) {
      if (!inc.title && !inc.body) continue; // analysis for an idea we don't have
      await db.put('ideas', { versions: [], tags: [], ...inc });
      stats.added++;
      if (inc.analysis) stats.analyzed++;
      continue;
    }
    // A file from Claude may contain only {id, analysis}; then only the analysis is merged.
    const base = inc.title !== undefined && newer(inc.updatedAt, mine.updatedAt) ? { ...mine, ...inc } : mine;
    const analysis = mergeAnalysis(mine.analysis, inc.analysis);
    if (analysis !== mine.analysis && inc.analysis) stats.analyzed++;
    if (base !== mine) stats.updated++;
    await db.put('ideas', { ...base, analysis });
  }
  return stats;
}

export async function getMeta(key) {
  return (await db.get('meta', key))?.value;
}

export async function setMeta(key, value) {
  await db.put('meta', { id: key, value });
}
