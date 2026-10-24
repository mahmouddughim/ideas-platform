# Exchange format with Claude

The app exports and imports a single JSON file. The same file is a full backup.

```json
{
  "format": "ideas-platform",
  "version": 1,
  "exportedAt": "2026-10-24T09:00:00.000Z",
  "sections": [{ "id": "sec-tech", "name": "تقنية", "icon": "💻" }],
  "ideas": [
    {
      "id": "idea-...",
      "title": "...",
      "body": "...",
      "sectionId": "sec-tech",
      "projectType": "تطبيق / برمجة",
      "goal": "حل مشكلة",
      "audience": "personal | publish",
      "status": "draft | developing | ready | published | archived",
      "tags": ["..."],
      "createdAt": "...",
      "updatedAt": "...",
      "versions": [{ "at": "...", "title": "...", "body": "..." }],
      "analysis": null
    }
  ]
}
```

## What Claude sends back

Claude may return the full file, or only `{ "id", "analysis" }` for each idea it
analyzed (leave out `title` so local edits are never touched):

```json
{
  "format": "ideas-platform",
  "version": 1,
  "ideas": [
    {
      "id": "idea-...",
      "analysis": {
        "at": "2026-10-24T10:00:00.000Z",
        "by": "Claude",
        "summary": "ملخص قصير للفكرة وتقييمها",
        "popularity": { "score": 65, "label": "نسبة الرواج المتوقعة", "note": "لماذا هذه النسبة" },
        "similar": [{ "name": "مشروع مشابه", "url": "https://...", "note": "ما الفرق" }],
        "strengths": ["..."],
        "improvements": ["..."],
        "missed": ["..."],
        "suggestions": ["..."],
        "questions": [
          { "id": "q1", "type": "yesno", "text": "هل تستهدف السوق العربي أولاً؟" },
          { "id": "q2", "type": "text", "text": "من هو أول مستخدم تتخيله؟" }
        ]
      }
    }
  ]
}
```

## Answers

- `yesno` questions store `answer` as `yes`, `no` or `unsure`, plus an optional longer `note`.
- `text` questions store the text in `answer`.
- Each answered question gets `answeredAt`.

## Merge rules on import

- An idea that does not exist locally is added (if it has a title or body).
- Idea fields are replaced only when the file's `updatedAt` is newer than the local one.
- A newer `analysis` replaces the old one, but answers already given locally to
  questions with the same `id` are kept. Use stable question ids when re-analyzing.
