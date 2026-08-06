# 12 — Visual Search with CLIP

**"Show me a photo of a sweater — find patterns that look like it."**

This is Woolly's image-to-pattern search. It is a **separate path** from text hybrid
search. You do not need to understand transformers math — you need the intuition, the
pipeline, and the product decisions.

Read `03-semantic-search-embeddings.md` first if "embedding" still feels fuzzy. The idea
here is the same (turn something into a list of numbers, find nearest neighbors) — but the
"something" is a **photo**, not a sentence.

---

## The product problem (why this exists)

Text search asks: *"describe what you want."*

Sometimes the user cannot describe it. They have:

- A photo of a finished knit on Instagram
- A sweater they saw in a shop window
- Their own FO (finished object) and want a similar pattern

**Visual search** answers: *"find patterns whose photos look like this photo."*

**Interview one-liner:**
> "I added CLIP-based image-to-image search. Pattern photos are embedded offline into
> 512-dimensional vectors. At query time I embed the uploaded image the same way, then
> rank by cosine similarity in pgvector. I use a multi-crop blend so matching prefers
> fabric/garment texture over background and model pose."

---

## What CLIP is (junior-friendly)

**CLIP** = Contrastive Language–Image Pre-training (OpenAI, 2021). Woolly uses the open
`clip-ViT-B-32` model via `sentence-transformers`.

### The big idea

CLIP was trained on hundreds of millions of (image, caption) pairs from the internet.
During training it learned:

- Put an image and its matching caption **near each other** in the same number-space
- Push unrelated image/caption pairs **far apart**

So CLIP has a **shared embedding space** for images *and* text. In theory you could do
text→image search ("red cable-knit sweater") with the same vectors.

**Woolly currently uses only image→image:**

```
your uploaded photo  →  CLIP  →  512 numbers
pattern photo        →  CLIP  →  512 numbers   (done offline at seed/backfill time)
compare with cosine similarity → nearest pattern photos win
```

### Why "shared space" matters even if we only do image→image

It means CLIP wasn't trained as a random image compresser. It was trained to care about
**what the photo is of** in a way that lines up with language. That tends to make
"cable-knit cardigan on a person" cluster with other cable-knit cardigans — not just
"any photo with a beige background."

### Breaking down `clip-ViT-B-32`

| Piece | Meaning |
|---|---|
| `clip` | The training recipe (image + text contrastive learning) |
| `ViT` | Vision Transformer — the image side is a transformer, not a classic CNN |
| `B` | "Base" size (middle of the family; not Tiny, not Huge) |
| `32` | Images are split into 32×32-pixel patches before the transformer sees them |

**You do not need to implement ViT.** Woolly calls:

```python
vector = model.encode(image, normalize_embeddings=True)  # → 512 floats
```

### Training vs inference (same rule as text embeddings)

| | Training | Inference (Woolly) |
|---|---|---|
| Who does it? | OpenAI / model authors, once | Your Docker container, every search |
| What happens? | Adjust millions of weights on huge data | Frozen model: image in → vector out |
| Cost | Enormous (GPUs, weeks) | ~hundreds of ms on CPU for one image |

**Interview line:** "I use a pretrained CLIP model for inference only — no fine-tuning."

---

## How visual search differs from text search

| | Text hybrid search | Visual search |
|---|---|---|
| **Input** | String query + filters | Uploaded JPEG/PNG/WebP |
| **Endpoint** | `GET /patterns/semantic-search` | `POST /patterns/visual-search` |
| **Model** | Bi-encoder + cross-encoder | CLIP (`clip-ViT-B-32`) |
| **Vector size** | 384 (`embedding` column) | 512 (`image_embedding` column) |
| **When corpus is embedded** | During pattern seed | Separate image backfill (+ after seed) |
| **Reranking?** | Yes (cross-encoder) | No — raw CLIP similarity only |
| **Caching?** | Full list in Redis 30 min | Not cached (each upload is unique bytes) |
| **Pagination?** | Yes (offset/limit on cached list) | Single page of top-N (default 10) |
| **Loaded at startup?** | Yes (text models) | **No** — lazy load (~600MB RAM) |

**System-design takeaway:** visual search is a **second retrieval modality**, not a
bolted-on filter on the text pipeline. Same database, same UI cards, different index and
model.

---

## The map analogy (again), but for photos

Imagine every pattern photo is a pin on a giant map. Photos that *look similar* (same
silhouette, stitch texture, color vibe) sit near each other.

1. User uploads a photo → CLIP drops a new pin for that photo.
2. Database asks: "which stored pins are closest?"
3. Those patterns are the results.

**384 vs 512 dimensions:** text MiniLM uses 384 numbers; CLIP ViT-B-32 uses 512. They are
**different spaces**. You cannot compare a text embedding to an image embedding with the
current setup — wrong model, wrong column, wrong dimension. Don't mix them.

---

## Multi-crop blending (the clever part)

A raw CLIP embedding of a whole Ravelry photo often encodes:

- Model pose and body
- Background (living room, outdoors)
- Framing / how cropped the shot is

…more than the **actual knit fabric**.

Woolly's fix in `clip_service.py`:

1. Embed the **full image**
2. Embed a **center crop** (middle 65% of width and height)
3. Blend: `0.4 × full + 0.6 × center`
4. **Renormalize** the blended vector to length 1 (so cosine distance still makes sense)

```
full frame (scene, pose, background)     weight 0.4
center crop (mostly garment / fabric)    weight 0.6
                    ↓
            blended 512-dim vector
```

**Why center crop?** Pattern photos usually put the garment in the middle. Cropping
throws away some edges (hands, sofa, sky) and keeps more yarn texture.

**Critical consistency rule:** query-time uploads and offline corpus embeddings **must**
use the same crop fraction and weights. If you change the blend, old and new vectors live
in slightly different "dialects" of the space — ranking quality collapses. Then you must
re-run:

```bash
docker-compose exec backend python scripts/embed_images.py --re-embed
```

---

## End-to-end flow (say this out loud)

### Offline (index build) — before users search by photo

```
Pattern has image_url (Ravelry CDN link)
        │
        ▼
scripts/embed_images.py  (or seeding's image backfill)
        │
        ├─→ Download image bytes transiently (NOT stored on disk by Woolly)
        ├─→ Multi-crop CLIP embed → 512 floats
        └─→ SAVE into patterns.image_embedding
```

Also triggered after a successful seed run (`seeding.py` calls `embed_missing_images`).

### Online (user uploads a photo)

```
User picks a photo on Home
        │
        ▼
Frontend: POST multipart file → /patterns/visual-search
        │
        ▼
Backend validates: JPEG/PNG/WebP, max 10MB
        │
        ▼
clip_service.embed_image_bytes()  (lazy-loads CLIP on first use)
        │
        ▼
SQL: ORDER BY image_embedding <=> query_vector  LIMIT N
        │
        ▼
Return SemanticSearchResult with similarity as rerank_score
(so the existing relevance bar UI works without a special card)
        │
        ▼
Log search_events with search_type="visual", query="[image search]"
```

See: `backend/app/api/patterns.py` → `visual_search_patterns()`,
`backend/app/services/clip_service.py`, `frontend/src/pages/Home.tsx`.

---

## Lazy loading vs startup loading (system design)

| Model | When loaded | Why |
|---|---|---|
| Bi-encoder (text) | FastAPI lifespan (startup) | Almost every search needs it |
| Cross-encoder | FastAPI lifespan (startup) | Text hybrid path needs it |
| CLIP | **First visual search** (lazy singleton) | ~600MB RAM; text-only users shouldn't pay that cost |

```python
# Same double-checked locking singleton as the text models —
# but get_clip_model() is NOT called in lifespan.
def get_clip_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer("clip-ViT-B-32")
    return _model
```

**Trade-off:** the first visual search after a process start is slower (model load). Later
ones reuse the warm model. Docker still **pre-downloads** CLIP weights at image build
time so the first load doesn't hit HuggingFace over the network.

**Interview framing:** "I eagerly load models on the hot path and lazily load the heavy
cold-path model. That's a classic latency vs memory trade-off."

---

## Database: a second vector column

```sql
-- Text semantic / hybrid leg
embedding        vector(384)

-- Visual search (CLIP)
image_embedding  vector(512)   -- nullable; NULL until backfilled
```

Added in `init_db.py` with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` so existing DBs
upgrade without a manual migration dance.

**Why nullable?** Not every pattern has a photo, and backfill can fail on dead CDN URLs.
Visual search SQL is:

```sql
WHERE image_embedding IS NOT NULL
ORDER BY image_embedding <=> CAST(:vec AS vector)
LIMIT :limit
```

If zero rows have embeddings → API returns **503** with a hint to run `embed_images.py`.

**No IVFFlat on image_embedding yet:** at current corpus size, a sequential scan over a
few hundred/thousand 512-d vectors is fine. At larger scale you'd add an IVFFlat/HNSW
index the same way as the text `embedding` column.

---

## Why no cross-encoder reranking for images?

Text search has a cheap recall stage and an expensive precision stage (cross-encoder).

Visual search today is **one stage**: CLIP similarity is already comparing the actual
photos. There is no separate "image cross-encoder" in the stack.

Possible future upgrades (good "what next?" answers):

- Combine CLIP score with text hybrid when the user also types a query
- Use CLIP text encoder for "red cabled cardigan" → image retrieval
- Add a learned reranker trained on click data

---

## Why visual results aren't Redis-cached

Text queries repeat ("beginner hat"). Uploaded images are essentially unique byte blobs —
cache hit rate would be near zero, and keys would be huge or hashed awkwardly.

So visual search always computes. Analytics still logs latency and `search_type="visual"`.

---

## Frontend UX (keep it simple)

On `Home.tsx`:

- Mode is `"text"` or `"visual"`
- Photo upload triggers `visualSearchPatterns(file)` in `api/client.ts`
- Shows a small preview of the uploaded image next to the results label
- No pagination for visual mode (single top-N list)
- Typing a new text search clears visual mode and preview

Reuse of `SemanticSearchResult` / `rerank_score` is intentional: one card component, two
backends.

---

## Failure modes & design responses

| Failure | Response |
|---|---|
| Wrong file type | 415 — only JPEG/PNG/WebP |
| File > 10MB | 413 |
| Undecodable image | 422 |
| No `image_embedding` rows yet | 503 + seed/backfill hint |
| One CDN URL dead during backfill | Log + skip; continue the run |
| Change crop/blend weights | Must `--re-embed` whole corpus |
| Analytics INSERT fails | Logged; search still returns 200 |

---

## Seeding interaction

After patterns are upserted, seeding tries:

```python
embed_missing_images(session)  # only rows with image_url and NULL image_embedding
```

Failures are swallowed so a CLIP OOM or CDN blip doesn't mark the whole seed run failed.
You can always finish backfill with the dedicated script.

Also related (robustness, not CLIP-specific): seeding strips NUL (`\x00`) characters from
Ravelry payloads — Postgres rejects them in TEXT/JSONB — and skips individual bad patterns
without aborting the whole run.

---

## Interview questions for this topic

**Q: How does image search work in Woolly?**
A: "Pattern photos are embedded offline with CLIP into 512-dim vectors stored in
`image_embedding`. When a user uploads a photo, I embed it with the same multi-crop CLIP
pipeline and run a cosine nearest-neighbor query in Postgres. Results are the patterns
whose catalog photos are closest in that space."

**Q: What is CLIP?**
A: "A pretrained model that maps images and text into a shared embedding space. I use the
image encoder for image-to-image retrieval — no fine-tuning, inference only."

**Q: Why multi-crop?**
A: "Full-frame embeddings over-weight pose and background. Blending in a center crop shifts
similarity toward the garment itself. Query and corpus must use the same blend."

**Q: Why not load CLIP at startup like the text models?**
A: "It's ~600MB resident. Most traffic is text search. Lazy singleton loads it on first
visual query; Docker still pre-warms the weights into the image at build time."

**Q: Can you compare a text embedding to an image embedding?**
A: "Not with the current columns — MiniLM 384-d and CLIP 512-d are different spaces.
CLIP itself could do text→image if I used CLIP's text encoder into the same 512-d space;
that's a future enhancement, not what ships today."

**Q: How would you scale visual search?**
A: "Add an ANN index on `image_embedding`, move backfill to a worker queue, consider GPU
for CLIP encode, and optionally a dedicated vector store if Postgres becomes the bottleneck.
The API contract (upload → ranked patterns) can stay the same."
