# Job sources (as of 11 November 2026)

Checked with a real HTTP request from this project's test environment.
"Works" means the endpoint returned a parseable feed of real postings.
Optional-key sources were checked far enough to confirm the live contract
(401 or 400 asking for a key, not a missing route).

## Used (free, no key)

| Source | Endpoint | Notes |
| --- | --- | --- |
| Remotive | `https://remotive.com/api/remote-jobs` | Works. Catalog can be thin (a few dozen postings). |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` | Works. Paginated, mostly EU. |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs?count=50` | Works. A specific `tag=` often returns zero jobs; the script fetches a general page and filters locally. |
| RemoteOK | `https://remoteok.com/api` | Works. First array element is a legal notice, not a job. Their terms ask that the original URL is shown; the digest always includes it. |
| Himalayas | `https://himalayas.app/jobs/api?limit=20` | Works, cursor pagination. Query-string keyword filters were not reliable, so the script paginates recent pages and filters locally. |
| We Work Remotely | category RSS, e.g. `https://weworkremotely.com/categories/remote-product-jobs.rss` | Works. |
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs` | Works for a valid board token. A wrong token is HTTP 404; the scan continues. |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json` | Works for a valid site token (example: `palantir`). Many well-known names have left Lever and 404. |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` | Works for a valid board token (examples: `wealthsimple`, `hopper`, `notion`, `openai`, `linear`, `ramp`, `replit`). |

## Used (optional key)

| Source | Endpoint | Notes |
| --- | --- | --- |
| SerpAPI Google Jobs | `https://serpapi.com/search.json?engine=google_jobs` | Live: HTTP 401 "Invalid API key" without a key, which is the documented contract. Skipped when `SERPAPI_API_KEY` is unset. Get a key at https://serpapi.com/ |
| Adzuna | `https://api.adzuna.com/v1/api/jobs/{country}/search/1` | Live: HTTP 400 without `app_id` / `app_key`. Skipped when those env vars are unset. Register at https://developer.adzuna.com/ |
| USAJobs | `https://data.usajobs.gov/api/Search` | Live: HTTP 401 without `Authorization-Key`. Off by default in the example profile. Needs `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT` (an email). https://developer.usajobs.gov/ |

## Dropped (broken on the check date)

| Source | What happened |
| --- | --- |
| Indeed RSS (`https://www.indeed.com/rss?...` and `https://ca.indeed.com/rss?...`) | HTTP 404 HTML "Not Found". Indeed's HTML search itself returned 403. Not used. There is no supported public Indeed RSS or scrape path in this project. |
| The Muse public jobs API (`https://www.themuse.com/api/public/jobs`) | HTTP 404. Not used. |

## Never used

LinkedIn blocks automated access. This project does not scrape it.
