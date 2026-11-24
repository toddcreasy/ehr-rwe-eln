# Frontend

The RWE Workbench pages: [Next.js](https://nextjs.org), React, and Tailwind, built as a static export (`output: "export"` in `next.config.ts`). `npm run build` writes plain HTML and JavaScript to `out/`, which FastAPI serves at `/`; no Node server runs.

```bash
npm ci
npm run build                 # writes out/
cd .. && uv run fastapi dev   # http://127.0.0.1:8000, the API under /api and these pages at /
```

The pages fetch relative `/api/...` paths, so `npm run dev` on port 3000 has no API behind it; build and use FastAPI instead. `npm run lint` runs ESLint.

| Path | Page |
|---|---|
| `app/page.tsx` | Home: the sections as tabs, each with a live figure |
| `app/dq/` | Data quality runs |
| `app/tte/` | Trial emulation bias reports |
| `app/eln/` | ELN entries beside their extractions |
| `app/synth/` | Synthetic releases and data cards |
| `app/curation/` | Variant curation and the curator's decisions |
| `app/shell.tsx` | The header and section strip every page shares |

On AWS the app image (`Dockerfile` at the repo root) builds the frontend into the image, and CodeBuild builds that image; see [Deploy the app](../infra/terraform/README.md#deploy-the-app).
