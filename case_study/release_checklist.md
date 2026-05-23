# v1.0.0 release checklist

Steps to take this repo from end-of-Week-11 state to a tagged v1.0.0 release.
These need a live machine — they are not part of any unit-test pass.

## 1. Train Sentinel against real data (optional but recommended)

```bash
bash scripts/download_backblaze.sh
python scripts/train_sentinel.py
docker compose restart sentinel-frankfurt
docker logs dcops-sentinel-frankfurt | grep model_loaded
```

The training run prints `precision / recall / f1 / auc_pr` on a held-out
20% slice. If precision < 0.7 the Week-4 success criterion isn't met — the
rule layer still ships predictions either way; the model just doesn't gate.

## 2. Run the benchmark sweep

```bash
make demo
docker compose run --rm ollama-init
make seed
make bench
# → case_study/benchmark_results.json
# → case_study/benchmark_report.html
```

Open the HTML report. Copy the headline table verdicts into:
- `case_study/DRAFT.md` § Measured outcomes
- `case_study/metrics_template.md` § Headline + Per-category breakdown
- `README.md` headline metrics block (if present)

## 3. Visual review of the dashboard

```bash
cd apps/dashboard
npm install
npm run dev
# open http://localhost:3000
```

Walk all five routes. Take screenshots for the README:
- `/` fleet overview
- `/sites/frankfurt` after `make inject SCENARIO=gpu_ecc_failure SITE=frankfurt`
- `/incidents` with the detail panel open
- `/twin` (the Three.js view — the one that needs human eyes most)
- `/query` after asking "Which racks ran hottest in Frankfurt over the last hour?"

Save under `case_study/screenshots/`. Reference them in README.

## 4. Record the demo

Follow `case_study/demo_script.md`. ~10 minutes; recovery playbook at the bottom for the live moments that go sideways.

## 5. Final repo hygiene

```bash
make test            # 286 unit tests, no warnings, no exclusions
make lint            # ruff + mypy strict + eslint
make typecheck       # mypy strict on apps/
docker compose --profile demo config --quiet
```

Everything green → tag:

```bash
git add -A
git commit -m "Release v1.0.0 — DCOps Copilot

12-week solo build: 8 agents, 3-site federation, OSS LLM by default, 200-
scenario benchmark harness. See case_study/DRAFT.md for the writeup and
case_study/benchmark_report.html for measured outcomes.
"
git tag -a v1.0.0 -m "v1.0.0 — initial release"
git push origin main
git push origin v1.0.0
```

## 6. Post-release

- Convert `case_study/DRAFT.md` to a final form (drop the DRAFT marker, set the date).
- Open follow-up issues from `case_study/DRAFT.md § Roadmap beyond v1.0.0`.
- Publish the demo recording.

---

## Things this checklist does not do

- It does not modify any code. Every Week-1-through-Week-11 commit stands.
- It does not promise the benchmark numbers will hit the targets. They depend on the live stack and (optionally) on the trained Sentinel weights. Be honest in the writeup.
- It does not push to remote. The `git push` commands at the bottom are deliberate — the user runs them when they're ready.
