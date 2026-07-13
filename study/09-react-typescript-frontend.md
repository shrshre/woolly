# 09 — React & TypeScript Frontend

**The dining room: how Woolly's UI is built and how it talks to the backend.**

---

## What React is

**React** is a JavaScript library for building user interfaces. Its core idea: instead of
manually manipulating HTML elements whenever data changes ("when the results come back,
find the results div and update its innerHTML..."), you describe *what the UI should look
like for a given state*, and React figures out the minimum changes to make it so.

**Analogy:** instead of telling a painter "erase the old number from the scoreboard and
write the new one," you show them a picture of what the scoreboard should look like and
they figure out what needs to be repainted. You describe the desired state; React handles
the execution.

---

## Components: the building blocks

A React app is made of **components** — reusable, self-contained pieces of UI. Each
component is a function that returns HTML-like code (called JSX) describing what it should
render.

Woolly's components:

| Component | File | What it renders |
|---|---|---|
| `App` | `App.tsx` | Router, providers, nav, footer, route definitions |
| `Home` | `pages/Home.tsx` | Search page: hero, filters, results, pagination |
| `SearchBar` | `components/SearchBar.tsx` | Pill-shaped input + submit button |
| `FilterBar` | `components/FilterBar.tsx` | Craft, difficulty, free/paid, category filters |
| `PatternCard` | `components/PatternCard.tsx` | Result card: image, title, badges, relevance bar, save button |
| `Badge` | `components/Badge.tsx` | Small colored pill (Beginner, Free, etc.) |
| `SkeletonCard` | `components/SkeletonCard.tsx` | Gray loading placeholder |
| `Nav` | `components/Nav.tsx` | Top navigation with auth-aware links |
| `ProtectedRoute` | `components/ProtectedRoute.tsx` | Redirects to login if not authenticated |
| `Library` | `pages/Library.tsx` | Saved patterns (protected) |
| `Projects` | `pages/Projects.tsx` | WIP project tracker (protected) |
| `StitchCounter` | `pages/StitchCounter.tsx` | Stitch/row counter tied to a project |

**Analogy:** components are like **LEGO bricks**. `PatternCard` is a specific brick you
can use once or a hundred times. You compose them together to build the full page.

```tsx
// Each pattern in the results list gets its own PatternCard
{result.patterns.map(pattern => (
    <PatternCard key={pattern.id} pattern={pattern} />
))}
```

---

## State: the app's memory

**State** is data that the component remembers and that, when it changes, causes React to
re-render (update the UI).

`Home.tsx` has the main search state:

```tsx
const [query, setQuery] = useState("");
const [filters, setFilters] = useState<SearchFilters>({});
const [patterns, setPatterns] = useState<PatternSummary[]>([]);
const [total, setTotal] = useState(0);
const [page, setPage] = useState(1);
const [loading, setLoading] = useState(false);
const [paging, setPaging] = useState(false);  // separate from initial search loading
```

**The flow when a user searches:**
1. User types → `setQuery(...)` → input field updates
2. User submits → `setLoading(true)` → skeleton cards appear
3. API call: `searchPatterns(query, filters, {offset: 0, limit: 10})`
4. Response → `setPatterns(...)`, `setTotal(...)`, `setLoading(false)` → cards appear
5. User clicks page 2 → `searchPatterns(activeQuery, filters, {offset: 10, limit: 10})`
   → backend cache hit, instant response
6. If error → `setError(...)` → error message shows

## Auth state: AuthContext and ProtectedRoute

Woolly uses React Context for global auth state:

```tsx
// App.tsx wraps everything in providers
<AuthProvider>
  <SavedPatternsProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/library" element={
          <ProtectedRoute><Library /></ProtectedRoute>
        } />
      </Routes>
    </BrowserRouter>
  </SavedPatternsProvider>
</AuthProvider>
```

**AuthContext** (`auth/AuthContext.tsx`):
- On mount, calls `GET /auth/me` to check if user is logged in
- Exposes `{user, login, logout, register}` to any component
- `user` is `{id, email}` or `null`

**ProtectedRoute** (`components/ProtectedRoute.tsx`):
- If `user` is null → redirect to `/login`
- Otherwise render children

**SavedPatternsContext** (`auth/SavedPatternsContext.tsx`):
- Tracks which patterns the user has bookmarked
- `PatternCard` reads this to show filled/outlined bookmark icon
- Calls `POST/DELETE /patterns/{id}/save` on toggle

See `11-authentication-and-user-data.md` for the backend auth flow.

---

## React Router: multiple pages

Woolly is no longer a single-page search app. **React Router** handles client-side navigation:

| Route | Page | Auth required? |
|---|---|---|
| `/` | Home (search) | No |
| `/login`, `/signup` | Auth forms | No |
| `/library` | Saved patterns | Yes |
| `/projects` | WIP tracker | Yes |
| `/counter` | Stitch counter | Yes |
| `/grid-maker` | Color grid tool | No |

Navigation between pages doesn't reload HTML — React Router swaps components in the
same JavaScript bundle. The URL bar updates so users can bookmark and share links.

---

## TypeScript: types for JavaScript

**TypeScript** is JavaScript with type annotations. It adds a compile step that catches
type errors before your code runs.

**JavaScript without TypeScript:**
```javascript
function displayPattern(pattern) {
  console.log(pattern.nme);  // typo: "nme" instead of "name"
  // runs fine, just prints "undefined" — silent bug
}
```

**TypeScript:**
```typescript
interface PatternSummary {
  id: number;
  name: string;
  designer: string | null;
  ravelry_url: string | null;
  free: boolean | null;
}

function displayPattern(pattern: PatternSummary) {
  console.log(pattern.nme);  // ❌ compile error: "Property 'nme' does not exist on type 'PatternSummary'"
}
```

TypeScript catches the typo at development time, before any user ever hits the code.

**Why it matters:** Woolly's typed API client in `frontend/src/api/client.ts` defines
TypeScript interfaces that match the Pydantic models on the backend. If the backend
changes the response shape, TypeScript errors point exactly to which frontend code broke.
This is especially powerful for a full-stack developer who needs to keep both sides in sync.

---

## The typed API client

`frontend/src/api/client.ts` is the single place where the frontend communicates with the
backend:

```typescript
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface PatternSummary {
  id: number;
  name: string;
  designer: string | null;
  ravelry_url: string | null;
  photo_url: string | null;
  free: boolean | null;
  similarity_score?: number;
  rerank_score?: number | null;
  relevance_label?: string | null;  // "Strong match" / "Good match" / "Possible match"
  difficulty?: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: "include",  // sends httpOnly auth cookie
    ...init,
  });
  // ... error handling
}

export function searchPatterns(
  query: string,
  filters: SearchFilters = {},
  { offset = 0, limit = 10 } = {}
): Promise<PatternSearchResult> {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  if (filters.craft) params.set("craft", filters.craft);
  // ... other filters
  return request(`/patterns/semantic-search?${params}`);
}
```

**What this gives you:**
- One place to change if the backend URL changes
- `credentials: "include"` on every request for auth cookies
- Typed interfaces for search, auth, library, and projects
- Filter and pagination params built into `searchPatterns`

---

## Vite: the build tool

**Vite** (French for "fast") is the tool that:
1. Serves the React app in development with hot module replacement (instant updates as you
   edit files — no full page reload)
2. Bundles and optimizes everything for production (`npm run build` → a folder of static
   files ready for a web server)

**Why not Create React App?** Vite is significantly faster for both startup and hot reload,
uses modern JavaScript modules natively, and is now the industry standard for new projects.

Woolly's `vite.config.ts` just registers the React plugin:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

---

## Skeleton loading states: good UX, easy to explain

When a search is in progress (`loading === true`), Woolly shows three `SkeletonCard`
components — gray animated placeholder cards in the same shape as real pattern cards.

```tsx
{loading && (
  <>
    <SkeletonCard />
    <SkeletonCard />
    <SkeletonCard />
  </>
)}
```

**Why this is better than a spinner:**
- Users see that *results are coming* and in *what shape* — it sets expectations
- The page doesn't feel like it "jumped" when content appears — the layout is pre-established
- Feels faster even if it isn't — perceived performance matters as much as real performance

**This is a named UX pattern** worth mentioning: "skeleton screen" or "content placeholder."
Facebook, LinkedIn, YouTube all use this.

---

## The design system in CSS

All of Woolly's visual design lives in `frontend/src/styles.css` — a single CSS file
implementing the design system from `PRD files/woolly-design-doc.md`.

Key design decisions:
- **All colors are hardcoded hex values** (e.g. `#800020` for burgundy) — never CSS variables
  that could inherit dark mode colors from the browser
- **Light mode only** — `color-scheme: light` on the root element
- **Two fonts**: Playfair Display (serif, for titles) and Source Sans 3 (sans-serif, for body)
  — loaded from Google Fonts
- **Icons**: Tabler icon set via CDN — outline style only

This enforces that Woolly looks exactly the same in every browser, regardless of the user's
OS dark mode preference.

---

## What's wired up vs what's still on the backlog

Be honest in interviews about what's real vs. planned:

| UI element | Status | Notes |
|---|---|---|
| Search bar + filters | ✅ Real | Calls `/patterns/semantic-search` with craft, difficulty, free, category |
| Pattern cards with relevance | ✅ Real | Shows `rerank_score`, relevance label, difficulty badge |
| Pagination | ✅ Real | Offset/limit, backend caches full list |
| Skeleton cards | ✅ Real | Show during loading |
| Error state | ✅ Real | Shows API error messages |
| Suggestion chips | ✅ Real | Populate search input and trigger search |
| Save/bookmark button | ✅ Real | Persists to DB when logged in; prompts login when not |
| Sign in / Sign up | ✅ Real | JWT cookie auth |
| My library | ✅ Real | Protected route, lists saved patterns |
| Projects tracker | ✅ Real | Create/update/delete WIP projects |
| Stitch counter | ✅ Real | Persists stitch/row counts to project |
| Grid maker | ✅ Real | Client-side color quantization tool |
| Ravelry account connect | ❌ Backlog | Still using app-level Ravelry credentials |
| Recommendations engine | ❌ Backlog | |
| Image-to-pattern search | ❌ Backlog | |
| Public project pages | ❌ Backlog | |

**Interview framing:** "The core product loop is fully wired — search, save, track projects.
Ravelry OAuth and recommendations are on the backlog. I'm transparent about scope."

---

## How frontend and backend agree on data shape

This is a subtle architectural point worth knowing:

- **Backend:** defines the response shape with Pydantic models (`PatternSummary`,
  `PatternSearchResult`)
- **Frontend:** defines the same shape with TypeScript interfaces (same field names, same
  types)

These are manually kept in sync — if you add a field on the backend Pydantic model, you
also add it to the TypeScript interface. In the future, you could auto-generate the
TypeScript types from the FastAPI OpenAPI spec using a tool like `openapi-typescript` — but
manual sync is fine at this scale.

---

## Multi-page application with React Router

Woolly uses **React Router** for client-side navigation. There's still one HTML file
(`index.html`) and one JavaScript bundle, but React Router swaps page components based on
the URL — `/library`, `/projects`, `/counter`, etc.

Protected routes gate personal pages behind authentication. Public pages (search, grid maker,
login) are accessible to everyone.

---

## Interview questions for this topic

**Q: What is React?**
A: "A JavaScript library for building UIs by describing what the interface should look like
for a given state, and letting React figure out the minimum DOM updates needed. Instead of
manually manipulating HTML, I update state and React re-renders the affected components."

**Q: What does TypeScript add?**
A: "TypeScript adds static type checking to JavaScript. I define the shape of API responses
as TypeScript interfaces matching the Pydantic models on the backend. If the backend changes
a field, TypeScript errors point exactly to the affected frontend code — catching bugs at
compile time instead of at runtime."

**Q: What is Vite?**
A: "Vite is the build tool and development server. It serves the React app with instant hot
module replacement during development, and bundles/optimizes everything for production."

**Q: What is a skeleton loading state and why is it good UX?**
A: "A skeleton is a gray placeholder in the same shape as the expected content, shown while
data loads. It's better than a spinner because users can see what's coming and in what form,
the layout doesn't jump when content arrives, and it feels faster — perceived performance
is as important as real performance."

**Q: Walk me through your React architecture.**
A: "React Router for multi-page navigation. AuthContext provides global auth state from
httpOnly cookie sessions. SavedPatternsContext tracks bookmarks. The search page (Home) manages
query, filters, pagination, and loading state. ProtectedRoute gates library, projects, and
stitch counter behind login. A typed API client handles all backend communication with
`credentials: include` for cookies."

**Q: How does the frontend handle authentication?**
A: "AuthContext calls GET /auth/me on mount. Login/register set an httpOnly cookie via the
backend — the frontend never touches the JWT directly. Every API call uses `credentials:
include`. ProtectedRoute redirects unauthenticated users to /login."

**Q: How does pagination work with the cached backend results?**
A: "The frontend sends offset and limit with each search request. The backend caches the
full ranked list per query+filters, so page 2 is a cache hit — just a slice. The frontend
tracks the current page and total from the API's `total` field."

**Q: How does the frontend talk to the backend?**
A: "Typed API client in `api/client.ts`. Uses native `fetch` with `credentials: include`
for auth cookies. Search sends query + filters + pagination params. Response shapes match
Pydantic models on the backend. Errors wrapped in a custom `ApiError` class."
