---
name: job-scout
description: "Use when running a daily job-market scan, scoring new postings against a resume, or setting up the job-scout cron job."
version: 1.0.0
author: Vishranth Giridharan
license: MIT
metadata:
  hermes:
    tags: [blueprint, productivity, jobs, career]
    blueprint:
      schedule: "0 8 * * *"
      deliver: origin
      prompt: "Run the daily job-scout scan. Follow skills/job-scout/SKILL.md exactly. If script output is already in context, use it and do not fetch job sites yourself. If the first line is NO_NEW_MATCHES, respond with only [SILENT]. Otherwise send a short digest: title, company, location, one-line reason, and URL for each match. After sending, run the script again with --update-seen. Do not invent details that are not in the script output."
      no_agent: false
required_environment_variables:
  - name: SERPAPI_API_KEY
    prompt: "SerpAPI key for Google Jobs (optional)"
    help: "Get one at https://serpapi.com/ . Leave blank to skip Google Jobs."
    required_for: "optional Google Jobs results"
  - name: ADZUNA_APP_ID
    prompt: "Adzuna app id (optional)"
    help: "Register at https://developer.adzuna.com/ . Also set ADZUNA_APP_KEY."
    required_for: "optional Adzuna results"
  - name: ADZUNA_APP_KEY
    prompt: "Adzuna app key (optional)"
    help: "Register at https://developer.adzuna.com/"
    required_for: "optional Adzuna results"
---

# Job Scout

Daily job-market scan for Hermes Agent. A helper script talks to public job APIs, scores each posting against the user's profile and resume, drops anything already shown, and prints the top 5 to 10 matches. A Hermes cron job runs that script every morning and delivers the digest to Telegram.

## When to Use

- The user wants today's new job matches, a dry run of the scout, or to schedule the daily scan.
- A cron job named "Daily job scout" (or similar) fires. Follow the procedure below; do not freestyle a web scrape.

## Paths

After install, these are the defaults:

| What | Path |
| --- | --- |
| This skill | `~/.hermes/skills/job-scout/` |
| Helper script | `~/.hermes/skills/job-scout/scripts/job_scout.py` |
| Profile | `~/.hermes/job-scout/profile.yaml` (copied from `profile.example.yaml`) |
| Resume | path set in the profile (`resume_path`) |
| Seen list | `~/.hermes/job-scout/seen.json` |
| Last run | `~/.hermes/job-scout/last_run.json` |

Override with `--profile`, `--state`, `--last-run`, or the `JOB_SCOUT_PROFILE`, `JOB_SCOUT_STATE`, and `JOB_SCOUT_LAST_RUN` environment variables.

## Procedure

### Daily scan (cron or "run it now")

1. Do not scrape LinkedIn, Indeed, or any job board yourself. The helper script is the only fetcher.
2. If the cron job already ran the script (its stdout is in your context), use that output. Otherwise run:

   ```bash
   python3 ~/.hermes/skills/job-scout/scripts/job_scout.py \
     --profile ~/.hermes/job-scout/profile.yaml \
     --state ~/.hermes/job-scout/seen.json
   ```

3. If the first line is `NO_NEW_MATCHES`, respond with only `[SILENT]`. Cron delivery treats that marker as "say nothing."
4. If there are matches, send a short digest:
   - One header line with the date and the number of new matches.
   - For each job: title, company, location, a one-line reason it fits the profile, and the URL.
   - Keep each reason to one sentence. Ground it in the script's `Why:` line and the profile. Do not invent salary, location, or requirements that are not in the script output.
   - Mention failed sources in one short closing line, if any. Do not retry them.
5. After the digest has been composed (and, on a live cron run, delivered), mark those postings as seen so they are not shown again:

   ```bash
   python3 ~/.hermes/skills/job-scout/scripts/job_scout.py --update-seen \
     --state ~/.hermes/job-scout/seen.json \
     --last-run ~/.hermes/job-scout/last_run.json
   ```

   On a `--dry-run` or a user preview, skip this step.

### First-time setup

1. Confirm Hermes is installed, a model key is configured (`hermes setup` or `hermes model`), and the Telegram gateway is up (`hermes gateway setup`, then `hermes gateway start`). The cron ticker runs inside the gateway, so the gateway must stay running.
2. Copy this skill and the example profile. The repo's `scripts/install.sh` does that, or:

   ```bash
   mkdir -p ~/.hermes/skills ~/.hermes/job-scout
   cp -r skills/job-scout ~/.hermes/skills/job-scout
   cp profile.example.yaml ~/.hermes/job-scout/profile.yaml
   cp resume.example.txt ~/.hermes/job-scout/resume.example.txt
   ```

   Then edit `profile.yaml`: titles, locations, salary floor, must-haves, deal-breakers, keywords, resume path, and ATS board tokens. Point `resume_path` at a plain-text resume.
3. Test a scan without writing state:

   ```bash
   python3 ~/.hermes/skills/job-scout/scripts/job_scout.py \
     --profile ~/.hermes/job-scout/profile.yaml \
     --dry-run --verbose
   ```

4. Schedule the daily job. Installing a skill with a `blueprint` block only *suggests* a cron job; it does not create one. Either accept the suggestion with `/suggestions`, or create it yourself. `0 8 * * *` is 8:00 AM in the Hermes timezone (usually the VPS local time):

   ```bash
   hermes cron create "0 8 * * *" \
     --name "Daily job scout" \
     --skill job-scout \
     --script ~/.hermes/skills/job-scout/scripts/job_scout.py \
     --deliver origin \
     --workdir ~/.hermes/job-scout \
     "Run the daily job-scout scan. Follow the job-scout skill exactly. If script output is already in context, use it and do not fetch job sites yourself. If the first line is NO_NEW_MATCHES, respond with only [SILENT]. Otherwise send a short digest: title, company, location, one-line reason, and URL for each match. After sending, run the script again with --update-seen. Do not invent details that are not in the script output."
   ```

   `--deliver origin` sends the result back to the chat where the job was created (Telegram, if you created it from Telegram). Use `--deliver telegram` to always send it there.

   For a cheaper run that skips the LLM and delivers the script output as-is, add `--no-agent` and `--script ~/.hermes/skills/job-scout/scripts/scan_and_mark.py` (that wrapper updates the seen list in the same pass).

5. Confirm the scheduler is alive: `hermes cron status`. Run once immediately with `hermes cron run <job-id>`.

### Changing the schedule

```bash
hermes cron list
hermes cron edit <job-id> --schedule "0 7 * * 1-5"   # 7:00 AM on weekdays
hermes cron pause <job-id>
hermes cron resume <job-id>
```

Natural phrases such as `every day at 8am` also work if the `croniter` package is installed (it ships with Hermes).

## Quick Reference

| Command | Purpose |
| --- | --- |
| `job_scout.py --dry-run` | Scan and print; no state writes |
| `job_scout.py` | Scan, print, write `last_run.json` |
| `job_scout.py --update-seen` | Mark last-run matches as seen |
| `job_scout.py --update-seen-after-scan` | Scan and mark in one pass |
| `job_scout.py --json` | Machine-readable output |
| `job_scout.py --sources greenhouse,ashby` | Limit to named sources |

## Sources

The script only calls APIs and feeds that allow automated access. LinkedIn is not used. Indeed's public RSS feed returned HTTP 404 on 11 November 2026 and is not used.

Free, no key (verified working on 11 November 2026): Remotive, Arbeitnow, Jobicy, RemoteOK, Himalayas, We Work Remotely RSS, Greenhouse, Lever, Ashby (the last three for company boards listed in the profile).

Optional keys: SerpAPI (Google Jobs), Adzuna, USAJobs. Each is skipped with a clear note when its key is absent.

If a source fails, report it as a coverage gap. Never treat a failed source as "no jobs today."

## Pitfalls

- Cron jobs run in a fresh session. The prompt must be self-contained; this skill and the `--script` output provide that context.
- `[SILENT]` only applies to successful empty runs. Hard failures still notify the delivery target unless `--failure-deliver local` is set.
- The seen list is what prevents repeats. If you skip `--update-seen` after a real delivery, tomorrow's digest will show the same jobs. If you mark them seen before a failed delivery, those jobs will not be retried. Prefer marking after a successful send.
- US-only remote roles are excluded when the profile is Canada-only, even if `remote_ok` is true. "Remote, CA, US" is California, not Canada.
- Salary floors are not converted across currencies. A USD figure is not compared to a CAD floor.
- Greenhouse board tokens are not company display names. A wrong token returns 404; the scan continues with the other boards.
- The Remotive catalog can be thin; a low count there is not a script bug.

## Verification

- [ ] `--dry-run` against the example profile returns real postings with URLs.
- [ ] A second run with `--update-seen-after-scan`, then a third run, does not repeat those URLs.
- [ ] `hermes cron status` shows the scheduler running before you rely on the 8 AM job.
