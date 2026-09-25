---
name: "Chunk by topic, not by size"
tags: [note-chunking, happy-path]
runs: 3
allowed_tools: [Read]
---

Read `test-notes/cs101_lecture05_recursion.txt` and chunk it into the notes JSON schema this project uses:

```json
{
  "lecture_id": "string",
  "date": "YYYY-MM-DD",
  "topics": ["string"],
  "chunks": [{"id": "string", "text": "string"}]
}
```

Show me the resulting JSON.
