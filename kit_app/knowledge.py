from __future__ import annotations

import io
import re
from typing import Any

from pypdf import PdfReader
try:
    from rank_bm25 import BM25Okapi
except ImportError:  # A small compatible BM25 implementation keeps local startup graceful.
    import math
    from collections import Counter

    class BM25Okapi:
        def __init__(self, corpus, k1=1.5, b=0.75):
            self.corpus = corpus
            self.k1, self.b = k1, b
            self.lengths = [len(doc) for doc in corpus]
            self.avgdl = sum(self.lengths) / max(1, len(self.lengths))
            self.freqs = [Counter(doc) for doc in corpus]
            self.df = Counter(term for doc in corpus for term in set(doc))

        def get_scores(self, query):
            scores = []
            n = len(self.corpus)
            for doc, frequencies, length in zip(self.corpus, self.freqs, self.lengths):
                score = 0.0
                for term in query:
                    freq = frequencies.get(term, 0)
                    if not freq: continue
                    idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                    norm = freq + self.k1 * (1 - self.b + self.b * length / max(1, self.avgdl))
                    score += idf * freq * (self.k1 + 1) / norm
                scores.append(score)
            return scores

from .college import college
from .settings import COLLEGE_API, PARTICIPANT_KEY


class KnowledgeBase:
    def __init__(self):
        self.chunks: list[dict[str, str]] = []
        self.index = None

    async def refresh(self, session: dict | None = None):
        documents = await college.request("GET", "/v1/documents", session)
        rows = documents if isinstance(documents, list) else documents.get("documents", documents.get("items", []))
        chunks = []
        for doc in rows[:30]:
            doc_id = doc.get("id") or doc.get("document_id")
            if not doc_id: continue
            try:
                async with __import__("httpx").AsyncClient(timeout=15) as client:
                    r = await client.get(f"{COLLEGE_API}/v1/documents/{doc_id}/file", headers={"X-Participant-Key": PARTICIPANT_KEY})
                r.raise_for_status()
                if len(r.content) > 20 * 1024 * 1024:
                    continue
                reader = PdfReader(io.BytesIO(r.content))
                content = "\n".join(p.extract_text() or "" for p in reader.pages[:80])
                visibility = " ".join(str(doc.get(k, "")) for k in ("title", "name", "type", "category", "audience", "visibility")).lower()
                private = any(term in visibility for term in ("handbook", "lesson", "notes", "circular", "student", "teacher", "faculty", "internal", "rulebook"))
                for i in range(0, len(content), 1000):
                    value = content[i:i + 1200].strip()
                    if value: chunks.append({"text": value, "title": doc.get("title", doc.get("name", "KIT document")), "id": str(doc_id), "scope": "private" if private else "public"})
            except Exception:
                continue
        if chunks:
            self.chunks = chunks
            self.index = BM25Okapi([self._tokens(c["text"]) for c in chunks])
        return len(self.chunks)

    @staticmethod
    def _tokens(text: str): return re.findall(r"[a-z0-9]+", text.lower())

    def search(self, query: str, role: str = "visitor", limit: int = 4):
        if not self.index: return []
        scores = self.index.get_scores(self._tokens(query))
        found = sorted(zip(scores, self.chunks), key=lambda x: x[0], reverse=True)
        items = []
        for score, chunk in found:
            if role == "visitor" and chunk.get("scope") == "private": continue
            if score > 0: items.append({**chunk, "score": float(score)})
            if len(items) == limit: break
        return items


knowledge = KnowledgeBase()
