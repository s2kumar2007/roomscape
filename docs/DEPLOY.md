# Deployment (Cloudflare Pages primary, Vercel backup)

> Status: build, headers and the health check were verified locally. **Deployment to Cloudflare/Vercel itself has not been run** (it needs your account).

## 0. Build and check
```bash
cd viewer && npm ci && npm run build
python ../scripts/check_dist.py          # fails if any file > 25 MiB (Cloudflare Pages per-file limit)
```
`viewer/public/_headers` is copied into `dist/` (caching + CORS for `/scene/*`).

## 1. Cloudflare Pages (scene file <= 25 MiB)
```bash
npx wrangler login
npx wrangler pages project create namma-space --production-branch main
npx wrangler pages deploy dist --project-name namma-space
```
Your URL: `https://namma-space.pages.dev` (the CLI prints the exact one).

## 2. Scene file larger than 25 MiB -> serve it from R2
Pages limits: 25 MiB per file, 20,000 files, 100 header rules (Cloudflare docs, Pages > Limits).
```bash
npx wrangler r2 bucket create namma-scenes
# upload scene + meta + collision (add --remote if your Wrangler defaults to local storage)
for f in scene.splat meta.json collision.json; do npx wrangler r2 object put namma-scenes/room1/$f --file ../viewer/public/scene/$f; done
```
Dashboard: R2 > namma-scenes > Settings > enable **Public access** (r2.dev URL) and add a **CORS policy** allowing your Pages origin, GET/HEAD:
```json
[{ "AllowedOrigins": ["https://namma-space.pages.dev"], "AllowedMethods": ["GET","HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600 }]
```
(Check the field names against the current R2 CORS docs in the dashboard.) Then either:
* share `https://namma-space.pages.dev/?scene=https://pub-XXXX.r2.dev/room1/`, or
* bake it in: `VITE_SCENE_BASE=https://pub-XXXX.r2.dev/room1/ npm run build`, then delete `dist/scene/scene.*` before deploying.

GitHub Releases can also host the file, but **CORS for release assets is untested**; prefer R2.

## 3. Vercel backup
```bash
cd viewer && npx vercel --prod          # framework: Vite, output: dist; vercel.json supplies headers
```

## 4. Health check (after deploying)
```bash
pip install playwright && python -m playwright install chromium
python scripts/health_check.py --url https://namma-space.pages.dev --seconds 10 --screenshot health.png
```
Reports load time and average FPS; exit code 1 on page errors/timeouts. In headless CI the browser uses software WebGL, so FPS is NOT representative of a real GPU; run with `--headed` on your own machine for real numbers.
