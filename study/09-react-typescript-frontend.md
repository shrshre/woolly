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
| `App` | `App.tsx` | The whole page: nav, hero, search bar, results, footer |
| `SearchBar` | `components/SearchBar.tsx` | The pill-shaped input + submit button |
| `PatternCard` | `components/PatternCard.tsx` | One result card: image, title, badges, buttons |
| `Badge` | `components/Badge.tsx` | A small colored pill (Beginner, Free, etc.) |
| `SkeletonCard` | `components/SkeletonCard.tsx` | Gray loading placeholder while waiting |

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

`App.tsx` has four pieces of state:

```tsx
const [query, setQuery]   = useState("");          // what the user has typed
const [result, setResult] = useState(null);        // the API response
const [loading, setLoading] = useState(false);     // is a search in progress?
const [error, setError]   = useState(null);        // any error message
```

`useState` is a React **hook** — a function that gives a component its own persistent
memory. Each call returns `[currentValue, setterFunction]`.

**The flow when a user searches:**
1. User types → `setQuery("cozy winter sweater")` → `query` updates → input field shows text
2. User submits → `setLoading(true)` → spinner appears
3. API call goes out
4. Response comes back → `setResult(data)` + `setLoading(false)` → cards appear
5. If error → `setError("Something went wrong")` + `setLoading(false)` → error message shows

React automatically re-renders only the parts of the UI that depend on the changed state.
You never manually update the DOM — you just update state and React handles it.

**Analogy:** state is like a **scoreboard at a game**. When someone scores, you update the
scoreboard number. The scoreboard (React) automatically displays the new number — you don't
manually repaint the display.

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
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface PatternSummary {
  id: number;
  name: string;
  designer: string | null;
  ravelry_url: string | null;
  photo_url: string | null;
  free: boolean | null;
}

export interface PatternSearchResult {
  query: string;
  patterns: PatternSummary[];
  total: number | null;
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function searchPatterns(query: string): Promise<PatternSearchResult> {
  const url = `${API_BASE}/patterns/semantic-search?q=${encodeURIComponent(query)}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    const body = await response.json();
    throw new ApiError(response.status, body.detail ?? "Unknown error");
  }
  
  return response.json();
}
```

**What this gives you:**
- One place to change if the backend URL changes
- TypeScript knows the shape of every API response — autocomplete, type checking
- A custom `ApiError` class that carries the HTTP status code for error handling in the UI

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

## What's wired up vs what's placeholder

Be honest in interviews about what's real vs. fake:

| UI element | Status | Notes |
|---|---|---|
| Search bar | ✅ Real | Calls `/patterns/semantic-search` |
| Pattern cards with results | ✅ Real | Populated from API response |
| Skeleton cards | ✅ Real | Show during loading |
| Error state | ✅ Real | Shows API error messages |
| Suggestion chips | ✅ Real | Populate the search input and trigger search |
| Save/bookmark button | ⚠️ Visual only | Toggles state locally, not persisted |
| "My library" nav link | ❌ Placeholder | `href="#"` — does nothing |
| "Projects" nav link | ❌ Placeholder | `href="#"` — does nothing |
| "Sign in" button | ❌ Placeholder | No-op — auth not built yet |

"Save" button has local state (click it and it turns burgundy), but when you refresh the
page it's gone. Auth and a backend `saved_patterns` table are needed to persist it.

**Interview framing:** "I intentionally scoped the frontend to match what's working in the
backend. The save button, nav links, and sign-in are designed and visible so I can
demonstrate the full product vision, but I'm transparent that they're not wired to real
functionality yet."

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

## Single-page application (SPA)

Woolly is a **single-page application** — there's one HTML file (`index.html`) and one
JavaScript bundle. React renders everything in JavaScript; no new HTML page is fetched from
the server when you do things.

**Implication:** there's only one "page" (the search page). Future features like "My Library"
and "Projects" would be added using **React Router** — a library that fakes page navigation
in the browser without actually loading new HTML from the server.

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

**Q: How does the frontend talk to the backend?**
A: "Through a typed API client in `api/client.ts`. It uses the browser's native `fetch` API
to send HTTP GET requests to the backend's `/patterns/semantic-search` endpoint. All
request/response shapes are typed with TypeScript interfaces. Errors are caught and wrapped
in a custom `ApiError` class with the HTTP status code."
