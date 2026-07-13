# 11 — Authentication & User Data

**How Woolly knows who you are, what you've saved, and what you're working on.**

This covers JWT auth, the saved-patterns library, and the project tracker. It's lower priority
than the search stack, but you should be able to explain it confidently as a full-stack
developer.

---

## Why auth exists in Woolly

Search works without logging in. Auth unlocks **personal data**:

- **Saved patterns** — bookmark patterns to your library
- **Projects** — track works-in-progress (yarn, needles, progress, notes)
- **Stitch counter** — persist stitch/row counts per project

These features need to know *which user* owns the data. That's what auth provides.

---

## The auth flow: JWT in httpOnly cookies

### What happens when a user signs up

```
Browser                    FastAPI                     PostgreSQL
   │                          │                            │
   │  POST /auth/register     │                            │
   │  {email, password}       │                            │
   │ ────────────────────────>│                            │
   │                          │  hash password (bcrypt)    │
   │                          │  INSERT INTO users         │
   │                          │ ──────────────────────────>│
   │                          │                            │
   │                          │  create JWT (user_id, exp) │
   │  Set-Cookie: woolly_token│                            │
   │  {user json}             │                            │
   │ <────────────────────────│                            │
```

1. User submits email + password (min 8 chars)
2. Backend lowercases email, checks for duplicates (409 if exists)
3. Password hashed with bcrypt — never stored plaintext
4. User row inserted into `users` table
5. JWT created with `sub` (user ID), `email`, `iat`, `exp` (7 days default)
6. JWT set in httpOnly cookie — browser stores it automatically

See: `backend/app/auth/routes.py`, `backend/app/auth/security.py`

### What happens on subsequent requests

```python
# frontend/src/api/client.ts
const response = await fetch(`${API_URL}${path}`, { credentials: "include", ...init });
```

`credentials: "include"` tells the browser to attach the auth cookie to every API call.

On the backend, protected routes use:

```python
@router.post("/{ravelry_id}/save")
async def save_pattern(
    user: User = Depends(get_current_user),  # ← decodes JWT from cookie
    ...
):
```

`get_current_user` reads the cookie, decodes the JWT, looks up the user in the database,
and returns the `User` object. If the token is missing, invalid, or expired → 401.

---

## Why httpOnly cookies instead of localStorage?

| Approach | XSS risk | CSRF risk | Auto-sent |
|---|---|---|---|
| **localStorage + Authorization header** | High — any JS can read the token | Low | No — must manually attach |
| **httpOnly cookie** | Low — JavaScript cannot access it | Medium — mitigated with SameSite | Yes — browser attaches automatically |

Woolly uses **httpOnly cookies** with `samesite="lax"`:

```python
response.set_cookie(
    key=settings.auth_cookie_name,
    value=token,
    httponly=True,       # JS cannot read this — XSS protection
    samesite="lax",      # cookie not sent on cross-site POST — CSRF mitigation
    secure=settings.cookie_secure,  # HTTPS only in production
    max_age=settings.jwt_expires_days * 86400,
)
```

**Interview answer:** "I store the JWT in an httpOnly cookie so JavaScript can't access it —
if there's an XSS vulnerability, an attacker can't steal the token from localStorage. The
browser sends the cookie automatically on every request via `credentials: include`. I use
SameSite=Lax to mitigate CSRF. In production I'd set Secure=true for HTTPS-only transmission."

---

## Password security: bcrypt

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
```

- **bcrypt** is intentionally slow (cost factor) — makes brute-force attacks expensive
- Each hash includes a random salt — identical passwords produce different hashes
- Max password length 72 bytes (bcrypt limitation, enforced in Pydantic)

**Never** store or log plaintext passwords. The `users` table only has `password_hash`.

---

## Database schema for user data

### `users` table

```sql
id            SERIAL PRIMARY KEY
email         TEXT UNIQUE NOT NULL
password_hash TEXT NOT NULL
created_at    TIMESTAMP DEFAULT NOW()
```

### `saved_patterns` — join table (many-to-many)

```sql
user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE
pattern_id INTEGER REFERENCES patterns(id) ON DELETE CASCADE
created_at TIMESTAMP DEFAULT NOW()
PRIMARY KEY (user_id, pattern_id)
```

A user bookmarks a pattern by `ravelry_id` in the API, but the join table uses internal
`pattern_id` (foreign key to `patterns.id`). CASCADE delete means if a user or pattern is
deleted, saved entries go too.

### `projects` table

```sql
id           SERIAL PRIMARY KEY
user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE
pattern_id   INTEGER REFERENCES patterns(id) ON DELETE CASCADE
yarn         TEXT
needle_size  TEXT
notes        TEXT
progress_pct INTEGER DEFAULT 0       -- 0-100
stitch_count INTEGER DEFAULT 0
row_count    INTEGER DEFAULT 0
status       project_status ENUM     -- queue, active, hibernating, finished
created_at   TIMESTAMP
updated_at   TIMESTAMP
```

See: `backend/app/db/models.py`

---

## API endpoints for user features

| Endpoint | Auth? | What it does |
|---|---|---|
| `POST /auth/register` | No | Create account, set cookie |
| `POST /auth/login` | No | Verify credentials, set cookie |
| `POST /auth/logout` | No | Delete cookie |
| `GET /auth/me` | Yes | Return current user |
| `POST /patterns/{id}/save` | Yes | Bookmark a pattern |
| `DELETE /patterns/{id}/save` | Yes | Remove bookmark |
| `GET /users/me/library` | Yes | List saved patterns |
| `POST /projects` | Yes | Create a project from a pattern |
| `GET /projects` | Yes | List user's projects |
| `PATCH /projects/{id}` | Yes | Update yarn, notes, progress, stitch counts |
| `DELETE /projects/{id}` | Yes | Delete a project |

---

## Authorization: users only see their own data

Every user-data route checks ownership:

```python
def _get_owned_project(db: Session, user: User, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project
```

**Why 404 instead of 403?** Returning 404 for both "doesn't exist" and "exists but not yours"
prevents attackers from discovering which project IDs exist by probing different users.

Save/unsave is idempotent — saving an already-saved pattern is a no-op (204).

---

## Frontend auth architecture

### AuthContext — global auth state

```tsx
// frontend/src/auth/AuthContext.tsx
<AuthProvider>
  {/* wraps the whole app */}
</AuthProvider>
```

On mount, calls `GET /auth/me`:
- 200 → user is logged in, store `{id, email}` in context
- 401 → user is null (not logged in)

Login/register update context immediately after success (cookie is already set).

### ProtectedRoute — gate for personal pages

```tsx
<Route path="/library" element={
  <ProtectedRoute>
    <Library />
  </ProtectedRoute>
} />
```

If no user in context → redirect to `/login`. Otherwise render the page.

Protected pages: `/library`, `/projects`, `/counter` (stitch counter).

### SavedPatternsContext — bookmark state

Tracks which `ravelry_id`s the current user has saved. `PatternCard` reads this to show
filled/outlined bookmark icon. Optimistic updates on save/unsave.

---

## The stitch counter feature

The stitch counter (`/counter`) is a protected page tied to a project:

- User selects an active project
- Tap to increment `stitch_count` (counts every 10 stitches per row in the UI)
- `row_count` tracks completed rows
- Counts persist via `PATCH /projects/{id}` with `stitch_count` and `row_count`

This is a simple example of **stateful UI backed by authenticated API calls** — the
counter survives page refresh because counts live in PostgreSQL, not browser memory.

---

## CORS and credentials

Woolly's CORS config includes `allow_credentials=True`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # required for cookies cross-origin
    ...
)
```

Without this, the browser would block cookie transmission from `localhost:5173` to
`localhost:8000`. The front end must also use `credentials: "include"` on every fetch.

---

## What's NOT built yet (be honest in interviews)

| Feature | Status |
|---|---|
| Email verification | Not implemented |
| Password reset | Not implemented |
| Ravelry OAuth (connect your Ravelry account) | Not implemented — still using app-level Basic Auth for Ravelry API |
| Username/display name | Email only — backlog item |
| Public project pages | Not implemented |

**Interview framing:** "I built email/password auth with JWT cookies for Woolly's own user
accounts. Ravelry integration still uses app-level credentials — connecting a user's personal
Ravelry account via OAuth is on the backlog."

---

## Interview questions for this topic

**Q: How does authentication work in Woolly?**
A: "Email/password registration and login. Passwords are hashed with bcrypt. On success, the
server creates a JWT and sets it in an httpOnly cookie. The frontend sends `credentials:
include` on every request so the cookie travels automatically. Protected routes use a
FastAPI dependency that decodes the JWT and loads the user — missing or invalid tokens
return 401."

**Q: Why httpOnly cookies instead of storing the JWT in localStorage?**
A: "httpOnly cookies can't be read by JavaScript, which protects against XSS token theft.
The browser attaches them automatically. I pair this with SameSite=Lax for CSRF mitigation
and Secure=true in production for HTTPS-only transmission."

**Q: How do you ensure users only access their own data?**
A: "Every user-data route requires `get_current_user` via dependency injection. Project
and library queries filter by `user_id`. For updates and deletes, I verify ownership
before acting — returning 404 if the resource doesn't exist or belongs to another user,
which prevents ID enumeration."

**Q: Walk me through the saved patterns feature.**
A: "It's a many-to-many join table between users and patterns. The API accepts Ravelry IDs
(familiar to the frontend) and resolves them to internal pattern IDs. Save is idempotent —
POSTing twice doesn't error. The library endpoint joins saved_patterns with patterns and
returns the full pattern summary shape the frontend already knows."

**Q: What would you add to auth next?**
A: "Refresh tokens or shorter-lived access tokens for better security, password reset flow,
and eventually Ravelry OAuth so users can connect their own Ravelry accounts instead of
Woolly using app-level credentials."
