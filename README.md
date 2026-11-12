# hermes-job-scout

A job search assistant that runs on [Hermes Agent](https://github.com/NousResearch/hermes-agent), the open-source agent from [Nous Research](https://nousresearch.com/). Once a day (8:00 AM local time by default) it scans public job sources for your target roles and locations, scores each posting against your resume and profile, skips anything it has already shown you, and sends the top 5 to 10 matches to Telegram. Each match comes with a one-line reason it fits and a link.

This is a skill and a helper script you add to an existing Hermes install. It is not a fork of Hermes, and it does not include anyone's personal profile, memory, or API keys.

A later v1 will draft a tailored resume summary and cover letter for a job you pick. That is not in this release.

## What you get

- `profile.example.yaml` - titles, locations, remote flag, salary floor, must-haves, deal-breakers, keywords, resume path, max results, and schedule time.
- `skills/job-scout/` - a Hermes skill (`SKILL.md` plus helper scripts) that holds the scan, scoring, dedupe, and summary logic.
- A daily scheduled job, declared the way Hermes actually schedules work: a `metadata.hermes.blueprint` on the skill (8:00 AM, deliver to the origin chat) and a matching `hermes cron create` command. Installing the skill only *suggests* the job; you opt in by accepting `/suggestions` or by running the command yourself. `cron/job-scout.example.json` shows the authored fields Hermes stores; do not paste it into `~/.hermes/cron/jobs.json` by hand.
- `.env.example` - optional source keys and where to get them.
- `scripts/install.sh` - copies the skill and a starter profile into `~/.hermes`.

The helper script talks only to sources that publish a documented public feed or JSON API. It does not scrape LinkedIn. Indeed's public RSS feed was retired (HTTP 404 on 11 November 2026) and is not used.

## 20-minute setup on a cheap VPS

You need a small Linux VPS (Hermes is happy on a $5 plan), an SSH login, and a Telegram account. Ubuntu 22.04 or 24.04 is a good default. Set the machine timezone to your own so "8:00 AM" means 8:00 AM for you:

```bash
sudo timedatectl set-timezone America/Toronto   # or your zone
```

### 1. Install Hermes (about 5 minutes)

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc    # or source ~/.zshrc
hermes setup        # pick a model provider and paste its API key
```

Official docs: [Installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation) and [Quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart).

### 2. Connect Telegram (about 5 minutes)

```bash
hermes gateway setup
hermes gateway start
hermes gateway status
```

The setup wizard walks you through creating a bot with [@BotFather](https://t.me/BotFather), pasting the bot token, and allowlisting your Telegram user id. Full steps: [Telegram setup](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram). Send the bot a test message and wait for a reply before you continue.

The cron ticker runs inside the gateway process. Leave `hermes gateway start` running (or install it as a service the way the Hermes docs describe) or the 8 AM job will not fire. Check with `hermes cron status`.

### 3. Install this skill (about 2 minutes)

From a clone of this repository:

```bash
git clone <this-repo-url> ~/hermes-job-scout
cd ~/hermes-job-scout
./scripts/install.sh
```

That copies the skill to `~/.hermes/skills/job-scout/` and a starter profile to `~/.hermes/job-scout/profile.yaml` (existing profiles are left alone).

### 4. Configure your profile (about 5 minutes)

Edit `~/.hermes/job-scout/profile.yaml`:

- `target_titles` - every title you want, including close variants.
- `locations` - city, region, and country. A "Remote, Canada" posting matches a user who listed Toronto.
- `remote_ok` - include remote and "anywhere" roles. US-only remote roles are still excluded if your locations are all in Canada.
- `salary_floor` and `salary_currency` - jobs with a clearly lower published maximum are dropped. Jobs with no salary, or a salary in a different currency, are kept.
- `must_haves` / `deal_breakers` / `keywords` - scoring hints. Deal-breakers drop a posting; missing must-haves only lower the score.
- `resume_path` - a plain-text resume. The example file is a fictional Project Manager in Toronto; replace it with yours.
- `max_results` - 10 is the default (the digest aims for 5 to 10).
- `schedule_time` / `timezone` - documented here so the install helper and the skill agree. The real schedule lives on the Hermes cron job.
- `ats_boards` - Greenhouse, Lever, and Ashby board tokens (the slug in the company's careers URL, not the display name). The examples were live on 11 November 2026. Add companies you care about; remove any that 404.

Optional API keys go in `~/.hermes/.env` (see `.env.example`). The scan runs without them.

### 5. Test a run (about 2 minutes)

```bash
python3 ~/.hermes/skills/job-scout/scripts/job_scout.py \
  --profile ~/.hermes/job-scout/profile.yaml \
  --dry-run --verbose
```

`--dry-run` prints the digest and writes nothing. You should see real postings with titles, companies, reasons, and URLs. From this repo, without installing:

```bash
python3 skills/job-scout/scripts/job_scout.py \
  --profile profile.example.yaml \
  --dry-run
```

### 6. Schedule the daily job (about 1 minute)

Hermes will not silently create a recurring job when you install a skill. Either accept the blueprint suggestion in a Hermes chat (`/suggestions`, then `/suggestions accept N`) or create it yourself:

```bash
hermes cron create "0 8 * * *" \
  --name "Daily job scout" \
  --skill job-scout \
  --script ~/.hermes/skills/job-scout/scripts/job_scout.py \
  --deliver origin \
  --workdir ~/.hermes/job-scout \
  "Run the daily job-scout scan. Follow the job-scout skill exactly. If script output is already in context, use it and do not fetch job sites yourself. If the first line is NO_NEW_MATCHES, respond with only [SILENT]. Otherwise send a short digest: title, company, location, one-line reason, and URL for each match. After sending, run the script again with --update-seen. Do not invent details that are not in the script output."
```

`--deliver origin` sends the result back to the chat where you created the job. Use `--deliver telegram` to always send it there. `0 8 * * *` is 8:00 AM in the Hermes timezone, which is usually the VPS local time.

`--script` makes Hermes run the helper first and inject its stdout into the agent context. The agent writes the Telegram message and stays silent (`[SILENT]`) when there is nothing new. After a successful send it runs `--update-seen` so those URLs are not shown again.

To skip the LLM and deliver the script text as-is (cheaper, slightly drier prose):

```bash
hermes cron create "0 8 * * *" \
  --name "Daily job scout" \
  --no-agent \
  --script ~/.hermes/skills/job-scout/scripts/scan_and_mark.py \
  --deliver telegram \
  --workdir ~/.hermes/job-scout
```

Fire one run immediately with `hermes cron run <job-id>` (see `hermes cron list`).

## Changing the schedule

```bash
hermes cron list
hermes cron edit <job-id> --schedule "0 7 * * 1-5"   # 7:00 AM, weekdays only
hermes cron pause <job-id>
hermes cron resume <job-id>
```

Natural phrases such as `every day at 8am` also work. The cron ticker only runs while the Hermes gateway is up (`hermes cron status`).

## How scoring and dedupe work

Each new posting gets a score out of 100: title match (required), location, keywords, resume overlap, must-haves, and a small salary bonus. Postings below `min_score`, in the wrong location, below the salary floor, or matching a deal-breaker are dropped. A posting must match one of your target titles (seniority prefixes such as "Senior" are fine).

The seen list (`~/.hermes/job-scout/seen.json`) is keyed by normalized URL, source id, and a company+title fingerprint, so the same job from two URLs is only shown once. `--dry-run` never writes it. A normal scan writes `last_run.json`; `--update-seen` (or the `scan_and_mark.py` wrapper) adds those entries to the seen list.

## Sources (checked 11 November 2026)

Working, no key: [Remotive](https://remotive.com/api/remote-jobs), [Arbeitnow](https://www.arbeitnow.com/api/job-board-api), [Jobicy](https://jobicy.com/api/v2/remote-jobs), [RemoteOK](https://remoteok.com/api), [Himalayas](https://himalayas.app/jobs/api), [We Work Remotely](https://weworkremotely.com/categories/remote-product-jobs.rss) RSS, and the public JSON boards for [Greenhouse](https://developers.greenhouse.io/job-board.html), [Lever](https://github.com/lever/postings-api), and [Ashby](https://developers.ashbyhq.com/docs/public-job-board-api).

Working with an optional key (skipped cleanly when the key is absent): [SerpAPI Google Jobs](https://serpapi.com/google-jobs-api), [Adzuna](https://developer.adzuna.com/), [USAJobs](https://developer.usajobs.gov/).

Dropped: Indeed public RSS (HTTP 404 on both `indeed.com` and `ca.indeed.com`); The Muse public jobs API (HTTP 404). LinkedIn is not used.

Details and board-token notes are in `skills/job-scout/references/sources.md`.

## Development

The helper is standard-library Python 3.10+. No third-party packages are required.

```bash
python3 tests/test_job_scout.py
python3 skills/job-scout/scripts/job_scout.py --profile profile.example.yaml --dry-run
```

## Roadmap

- **v1 (later):** tailored resume summary and cover letter for a job you pick, sent back on Telegram.
- Possible follow-ups: apply tracking, more ATS boards, a weekly digest of what changed.

## License

MIT. Copyright (c) 2026 Vishranth Giridharan. Hermes Agent is a separate project with its own license; this repository only contains the job-scout skill and scripts.
