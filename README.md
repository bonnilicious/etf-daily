# ETF Daily — Setup Guide (one-time, ~15 minutes)

A fully automated, **rules-based** daily ETF digest website.
Once set up, it runs itself every morning on GitHub's free servers — no Mira,
no manual steps, no monthly bill, nothing to top up.

Tailored for a **Singapore investor using Interactive Brokers (IBKR)**.

---

## What's in this folder

| File | What it does |
|------|--------------|
| `generate.py` | The "brain": fetches free ETF data, applies the rules, writes `index.html` |
| `.github/workflows/daily.yml` | The automation: tells GitHub to run the brain every morning at 7am SGT |
| `index.html` | The generated website (created automatically each day) |
| `README.md` | This guide |

No API keys. No paid services. Data comes from Yahoo Finance's free public endpoint.

---

## Step 1 — Create a free GitHub account
1. Go to https://github.com and sign up (free). Skip if you already have one.

## Step 2 — Create a new repository
1. Click the **+** (top right) → **New repository**.
2. Name it e.g. `etf-daily`.
3. Set it to **Public** (required for free GitHub Pages + free Actions).
4. Click **Create repository**.

## Step 3 — Upload these files
1. On the new repo page, click **uploading an existing file**.
2. Drag in `generate.py` and `README.md`.
3. **Important:** the workflow must keep its folder path. Easiest method:
   - Click **Add file → Create new file**.
   - In the filename box, type: `.github/workflows/daily.yml`
     (typing the slashes auto-creates the folders).
   - Paste the contents of `daily.yml` into the editor.
   - Click **Commit changes**.

## Step 4 — Turn on Actions permissions
1. Go to **Settings → Actions → General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions** → **Save**.
   (This lets the daily job commit the updated page.)

## Step 5 — Run it once manually (to create the first page)
1. Go to the **Actions** tab.
2. Click **ETF Daily** in the left list → **Run workflow** → **Run workflow**.
3. Wait ~30 seconds. A green tick means it generated `index.html`.

## Step 6 — Publish the website with GitHub Pages
1. Go to **Settings → Pages**.
2. Under **Source**, choose **Deploy from a branch**.
3. Branch: **main**, folder: **/ (root)** → **Save**.
4. After a minute, your live site appears at:
   `https://YOUR-USERNAME.github.io/etf-daily/`

Done. From now on it updates itself every morning at **7:00 AM Singapore time**.

---

## How to customise (optional, anytime)

Open `generate.py` on GitHub and click the pencil icon to edit:

- **Change which ETFs are tracked** → edit the `CORE_ETFS` list.
- **Change the themed rotation** → edit the `THEMED_ETFS` list (one is featured per day, cycling through the list).
- **Change the run time** → edit the `cron` line in `daily.yml`.
  It's in UTC. `0 23 * * *` = 23:00 UTC = 07:00 SGT. For 8am SGT use `0 0 * * *`.

Commit the change and the next run uses it. No reinstall needed.

---

## Troubleshooting

- **Page shows "—" instead of prices:** Yahoo occasionally rate-limits. The next daily run usually fixes it; or re-run manually from the Actions tab.
- **Workflow failed (red X):** open the failed run → read the log. Most often it's Step 4 (write permissions) not being enabled.
- **Pages link 404s:** wait 1–2 minutes after first deploy, and make sure `index.html` exists in the repo.

---

## Important note

This tool is **rules-based and for personal information only — it is not financial
advice**. It ranks by simple daily momentum and rotates themes mechanically; it does
not know your goals or risk tolerance. Always do your own research before buying.
Niche themed ETFs are higher-risk satellite holdings — keep them small relative to
your diversified core.
