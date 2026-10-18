# Run and release Signaldesk

## Local portfolio demo

The supported full-stack target is a local demo. It binds the web app to loopback and includes the API, a PostgreSQL database, scheduled collectors, and static frontend. Compose starts in read-only public-demo mode: generated drafts, evidence packets, and traces are hidden, while X intake and generation are disabled. It does not require paid services. The app can collect and read sources without an inference key; direct local draft generation requires a compatible free-only key.

1. Install Docker Desktop with Compose, then copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD` with a long random alphanumeric value. Keep `.env` private; it is ignored by Git. The Compose demo does not need a model key.
3. Run `docker compose up --build` and open `http://127.0.0.1:8080`.
4. Check `http://127.0.0.1:8080/health`, then review the feed, model radar, and source status. This Compose configuration keeps private drafts and the X/manual input form disabled.
5. Stop with Ctrl+C and run `docker compose down`. The named PostgreSQL volume is retained. `docker compose down -v` deletes that local database.

The local developer setup uses SQLite and can be run without Docker using the README commands. CI runs the regression suite and frontend production build. `docker compose config --quiet` validates the Compose file without starting containers. A successful config check does not prove that the images build or PostgreSQL works at runtime.

## Public demo and full-service hosting

The public demo is a static GitHub Pages build. The workflow collects public sources every six hours, exports a sanitized JSON snapshot, and deploys the frontend. It includes bounded, attributed excerpts and model-card metadata, with no user data, generated drafts, evidence queue, provider credentials, or write endpoints. A small history file stores model identifiers, download counts, and observation times so 24-hour and 7-day changes can build across stateless runners. The current and prior snapshots remain in the public repository's Git history; all included content is public source material with attribution and links. If fewer than five sources succeed, the workflow keeps the last committed snapshot; the initial snapshot is generated from a clean database using the same collector/export steps. The local snapshot exporter and frontend demo mode can be checked with:

```powershell
uv run python -m backend.export_demo --output frontend/public/demo-data.json
cd frontend
npm ci
$env:VITE_DEMO_MODE = 'true'
$env:VITE_BASE_PATH = '/signaldesk/'
npm run build:demo
```

GitHub Pages uses the Actions source; the publish workflow runs on pushes to `main`, every six hours, or manually. A public static deployment can be released independently of the interactive API. The project includes an MIT license; publisher content remains attributed and linked to its original source. No static public URL exists until the repository is published and the workflow completes.

The full API is not ready for public hosting. It has no user authentication or roles, and the local draft action is not an editorial authorization system. Do not expose the API stack or change its loopback binding to a public interface. Before hosting the full service, complete and verify all of these:

- Add authentication, role checks, CSRF protection for browser mutations, and rate limits; disable all local-only intake and generation flags by default.
- Validate migrations and worker operation against PostgreSQL on the intended host, then exercise backup and restore from an off-host backup.
- Configure production-only secrets, restrictive network access to PostgreSQL, HTTPS, secure headers, and an authenticated admin allowlist.
- Run desktop and mobile smoke checks, inspect a representative sample of generated drafts, and publish a privacy/data-retention notice for any hosted user data.
- Set up the public repository, CI run, code license, domain/DNS, monitoring, and rollback procedure. The current checkout has no Git remote, and no external cloud resources have been created.

Do not describe the synthetic 20-case evaluation as model accuracy. Its current rubric and limitations are documented in `evals/README.md`.
