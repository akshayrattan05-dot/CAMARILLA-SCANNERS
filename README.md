# Camarilla R5 Scanner — Setup Guide

Scans every USDT-margined perpetual futures pair on Binance every 15 minutes.
Sends a Discord alert when a symbol has TWO CONSECUTIVE closed 15-minute
candles that are both green AND closed above that symbol's daily R5 level.

## IMPORTANT — verify the R5 formula first

Open your TradingView chart, find BTC's current R5 value, and compare it
to what this script calculates. Camarilla only has one agreed formula up
through R4 — R5 has two competing conventions. This script defaults to
`R5 = (High/Low) * Close`. If that doesn't match your chart, open
`scan_camarilla.py` and change `R5_FORMULA = "a"` to `R5_FORMULA = "b"`
near the top of the file (that version uses `R5 = R4 + 1.168*(R4-R3)`).

You can test this instantly: run the script once manually (see "Testing"
below) — it prints the R5 value it calculated for every symbol it checks.

## Step 1 — Create a Discord webhook

1. Open Discord, go to the server you want alerts in
2. Server Settings → Integrations → Webhooks → New Webhook
3. Pick the channel, give it a name (e.g. "Camarilla Alerts")
4. Click "Copy Webhook URL" — keep this private, treat it like a password.
   Anyone with this URL can post messages into that channel.

## Step 2 — Create a GitHub repository

1. Go to github.com, create a new repository (e.g. `camarilla-scanner`)
2. Upload these three files, keeping the folder structure exactly as-is:
   - `scan_camarilla.py`
   - `.github/workflows/camarilla-scan.yml`
   - `README.md` (this file)

   Note: GitHub's web upload UI doesn't always let you create the nested
   `.github/workflows/` folder directly. Easiest way: on the repo page,
   click "Add file" → "Create new file", type
   `.github/workflows/camarilla-scan.yml` as the filename (GitHub will
   auto-create the folders), then paste the workflow content in.

## Step 3 — Add your Discord webhook as a secret (do NOT paste it into the code)

1. In your new GitHub repo: Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste your Discord webhook URL from Step 1
5. Save

## Step 4 — Enable and test

1. Go to the "Actions" tab in your repo
2. You should see "Camarilla R5 Scanner" listed as a workflow
3. Click it, then click "Run workflow" (this is the manual trigger, for
   testing without waiting for the schedule)
4. Watch the run — click into it to see the live log, including the R5
   value calculated for each symbol (use this to verify against your
   TradingView chart)
5. Once confirmed correct, it will run automatically every 15 minutes
   from then on — no further action needed

## Rate limits

Binance allows up to 2400 request-weight per minute on the futures API.
This script paces requests (0.15s between each) and typically completes
a full scan of all USDT-M perpetuals well within that limit. If Binance
adds many more symbols in the future and the scan starts taking longer
than ~13 minutes (cutting it close to the next 15-minute run), let me
know and we can parallelize or shard the symbol list.

## Costs

This is free. GitHub Actions gives generous free minutes for public
repositories (and a solid free allowance for private ones too), and
Binance's public market data API requires no key and no payment.
