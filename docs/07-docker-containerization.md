# 07 — Docker & Containerization

**The building: how Woolly runs identically on any machine, with one command.**

---

## The problem Docker solves

"It works on my machine" is the most famous phrase in software development — and it's
a real, painful problem. Before containers:

- Developer A has Python 3.11 installed. Developer B has Python 3.9. Code that works for
  A breaks for B.
- The app needs PostgreSQL 16, but B's machine has 13 installed.
- The app needs a specific version of a C library that's installed differently on Mac vs Linux.
- Deploying to a server means manually installing every dependency in exactly the right
  version — a process that's error-prone and hard to repeat.

Docker solves all of this by packaging an application together with *everything it needs to
run* — the language runtime, libraries, OS utilities — into a single portable unit called
a **container**.

**Analogy:** think of a Docker container as a **shipping container** on a cargo ship. Before
shipping containers, every port loaded cargo differently — different sizes, different
handling, different equipment. After standardized shipping containers, a container loaded in
Shanghai arrives and unloads in Los Angeles using the exact same process. The contents don't
matter to the port — the container interface is standard. Docker does the same for software.

---

## Images vs containers: the blueprint vs the building

Two core concepts to keep straight:

**Image** = the blueprint (read-only template)
- Defined by a `Dockerfile`
- Contains: OS base layer, language runtime, your app's files, dependencies
- Immutable — you can't change a running image
- Analogy: a **cake recipe** — complete instructions for making the thing

**Container** = a running instance of an image
- Created from an image with `docker run` (or by docker-compose)
- Has its own filesystem, network, and process space
- Can be started, stopped, restarted
- Multiple containers can run from the same image simultaneously
- Analogy: the **actual cake** made from the recipe — you can make many cakes from one recipe

```
Dockerfile → (build) → Image → (run) → Container
```

---

## The backend Dockerfile, explained line by line

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim
# Start from an official Python 3.12 image (a minimal Linux + Python pre-installed)
# "slim" means no extras — keeps the image small

WORKDIR /code
# All subsequent commands run in /code directory inside the container

COPY requirements.txt .
RUN pip install -r requirements.txt
# Install Python dependencies FIRST (before copying code)
# Why? Docker caches each step. If only code changes (not requirements),
# Docker reuses the cached pip install step → faster rebuilds

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
# Pre-download the bi-encoder at BUILD time, not at runtime
# Without this, the first startup would download ~90MB while users wait

RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"
# Same warmup for the cross-encoder reranker (~90MB). Both models load into memory
# during FastAPI lifespan; baking weights into the image avoids HuggingFace downloads
# on every fresh container.

COPY ./app /code/app
# Copy your actual application code into the container

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# The command that runs when the container starts
# uvicorn is the ASGI server that runs the FastAPI app
# "--host 0.0.0.0" makes it accessible from outside the container
```

**Key insight:** dependencies are installed before code is copied. This is deliberate.
Docker builds images in layers and caches each step. If you change one line of Python code
but not `requirements.txt`, Docker reuses the cached dependency layer and only rebuilds
the code layer. This makes iterative development much faster.

---

## The frontend Dockerfile

`frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine
# Node.js 20 on Alpine Linux (very small Linux distribution)

WORKDIR /code
COPY package.json package-lock.json ./
RUN npm install
# Same layer-caching trick: install dependencies first

COPY . .
# Copy all frontend code

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
# Run the Vite dev server, accessible from outside the container
```

Note: this runs Vite in **development mode** (hot reload, no optimization). For production,
you'd run `npm run build` to produce static files and serve them with Nginx. The PRD notes
this is on the roadmap.

---

## docker-compose: the master switch

Running four separate `docker run` commands for the four services would be tedious and
error-prone. `docker-compose.yml` is a config file that defines all four services and their
relationships, and starts/stops them all with one command.

```yaml
services:
  db:                           # PostgreSQL
    image: pgvector/pgvector:pg16    # official image with pgvector pre-installed
    environment:
      POSTGRES_DB: woolly
      POSTGRES_USER: woolly
      POSTGRES_PASSWORD: woolly
    volumes:
      - postgres_data:/var/lib/postgresql/data   # persist data across restarts
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U woolly"]  # wait until DB is ready

  redis:                        # Redis
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  backend:                      # FastAPI
    build: ./backend            # build from backend/Dockerfile
    ports:
      - "8000:8000"             # expose port 8000 to your laptop
    env_file: .env              # load environment variables from .env file
    depends_on:
      db:
        condition: service_healthy   # don't start until DB is ready
      redis:
        condition: service_healthy
    volumes:
      - ./backend/app:/code/app  # mount local code into container (hot reload!)

  frontend:                     # React
    build: ./frontend
    ports:
      - "5173:5173"
    environment:
      - VITE_API_URL=http://backend:8000  # frontend calls backend by service name
    depends_on:
      - backend
    volumes:
      - ./frontend/src:/code/src   # hot reload for frontend too
```

### What this gives you

- `docker-compose up` starts all four services in the right order (db and redis first,
  then backend, then frontend)
- `docker-compose down` stops and removes all containers
- Services refer to each other by name (`backend`, `db`, `redis`) — Docker handles the
  network routing internally

---

## The private network: how containers talk to each other

When docker-compose creates services, they're all on a private virtual network. Services
find each other by name — not `localhost` or an IP address.

```
backend container → db container
  connects to: "db:5432"      (not "localhost:5432")
  
backend container → redis container
  connects to: "redis:6379"   (not "localhost:6379")
  
frontend container → backend container
  connects to: "http://backend:8000"
```

But your laptop's browser connects to `localhost:5173` and `localhost:8000` — the ports
that docker-compose exposes to the host machine.

**Analogy:** the containers are like offices in a building. Inside the building, employees
(containers) reach each other by name: "go talk to the person at desk 'db'". From the
street (your laptop), you enter through the building's front door (the exposed ports).

---

## Volumes: hot reload and persistent data

Docker containers have ephemeral filesystems — if you stop and remove a container, its
filesystem is gone. For two use cases, you need data to survive:

**1. Hot reload during development** — when you edit a Python file, the server should
restart with the new code without rebuilding the image:

```yaml
volumes:
  - ./backend/app:/code/app   # map local ./backend/app to /code/app inside container
```

Now your code editor saves a file to `./backend/app/main.py` on your laptop, and the
container sees the change instantly at `/code/app/main.py`. Uvicorn watches for file
changes and auto-reloads. Same for frontend — edit `./frontend/src/App.tsx`, the browser
instantly shows the change.

**2. Persistent database data** — PostgreSQL data should survive `docker-compose down`:

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data  # named volume, managed by Docker
```

`postgres_data` is a named volume — Docker stores it on your filesystem and re-attaches
it every time the `db` service starts. So patterns you seeded yesterday are still there
today.

---

## Healthchecks: starting services in the right order

The backend needs the database to be ready before it can run queries. Without healthchecks,
docker-compose starts everything simultaneously — the backend starts, tries to connect to
the database that isn't ready yet, crashes.

Healthchecks fix this:

```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U woolly"]   # periodically run this command
    interval: 5s
    timeout: 5s
    retries: 5

backend:
  depends_on:
    db:
      condition: service_healthy   # wait until db reports healthy
```

PostgreSQL's `pg_isready` command returns 0 (success) when the database is accepting
connections. Docker polls it every 5 seconds. The backend only starts after this succeeds.

**Analogy:** a chef doesn't start cooking if the kitchen's gas isn't on yet. The
`depends_on` condition is the chef checking that the stove works before beginning prep.

---

## Why this matters for deployment (AWS-readiness)

The PRD explicitly says Woolly is "AWS-ready from day one." Here's why Docker achieves that:

1. **Same containers:** the exact same images that run locally can be deployed to AWS ECS
   (Elastic Container Service). No changes to the code.
2. **Environment variables:** all configuration is in `.env` locally; in AWS, it comes from
   ECS task definitions or AWS Secrets Manager. Same code, different injection point.
3. **Stateless backend:** the FastAPI server doesn't store anything locally — it reads from
   the database and cache, which are external services. You can run 10 backend containers
   behind a load balancer and any of them can handle any request.

**Interview answer for "how would you deploy this?"**
"The Docker containers already define the deployment unit. I'd push the images to AWS ECR
(Elastic Container Registry), run the backend on ECS, replace the docker-compose PostgreSQL
with AWS RDS, replace Redis with ElastiCache, and put CloudFront in front of the frontend
static files on S3. The code doesn't change — only the environment variables."

---

## Interview questions for this topic

**Q: Why Docker? What problem does it solve?**
A: "Docker eliminates 'it works on my machine' by packaging the app with everything it
needs to run — language runtime, libraries, OS utilities — into a portable container.
The same image runs identically on my laptop, a teammate's machine, and an AWS server."

**Q: What's the difference between a Dockerfile and docker-compose.yml?**
A: "A Dockerfile is the recipe to build a single image — it defines what goes inside one
container. docker-compose.yml orchestrates multiple containers together: which services to
run, how they connect, their environment variables, port mappings, and startup order."

**Q: What are volumes used for in Woolly?**
A: "Two things: code volumes mount local files into containers for hot reload during
development — I edit a file on my laptop and the container sees it immediately. A named
volume for PostgreSQL persists the database data so it survives container restarts."

**Q: How would you deploy this on AWS?**
A: "Push Docker images to ECR, run backend containers on ECS Fargate, swap the local
PostgreSQL for RDS (PostgreSQL-compatible with pgvector support), swap Redis for
ElastiCache, build the frontend and serve static files from S3 with CloudFront. The code
is unchanged — only environment variables point to different services."

**Q: What is a health check and why does Woolly use one?**
A: "A health check is a command Docker runs periodically to verify a service is ready.
Woolly uses `pg_isready` on the database container. The backend's `depends_on` waits for
the database to pass the health check before starting — so the backend never tries to
connect to a database that isn't ready yet."
