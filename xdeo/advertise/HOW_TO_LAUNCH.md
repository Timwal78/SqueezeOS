# How to Launch xDEO — Click by Click

Plain English. No coding. You're pressing buttons on GitHub.

Everything happens on this page:
**https://github.com/Timwal78/SqueezeOS/actions**

That's your repo → the **"Actions"** tab at the top.

---

## ⓪ One-time setup: add the admin token (do this ONCE, first)

The seeding step needs a password called `XDEO_ADMIN_TOKEN`. You make it up — it just has to match in two places. Here's the safe way:

1. Make up a long random password. Easiest: open a new browser tab, go to https://www.random.org/passwords/?num=1&len=24&format=plain and copy what it shows. (Or mash your keyboard — just make it long.)
2. Go to: **https://github.com/Timwal78/SqueezeOS/settings/secrets/actions**
3. Click the green **"New repository secret"** button.
4. **Name:** type exactly `XDEO_ADMIN_TOKEN`
5. **Secret:** paste your random password.
6. Click **"Add secret"**.

✅ Done. You never need to see that password again — GitHub keeps it encrypted. The deploy workflow reads it automatically.

> **Note:** You also need `CLOUDFLARE_API_TOKEN` and `X402_PAY_TO` as secrets. If xDEO is already live (it is), those are already set. If a deploy fails complaining about them, that's the only reason — but they should already be in place from the original setup.

---

## ① Deploy the latest code

This pushes the newest version of xDEO live.

1. Go to **https://github.com/Timwal78/SqueezeOS/actions**
2. In the left sidebar, click **"xdeo-deploy"**.
3. On the right, click the gray **"Run workflow"** dropdown button.
4. Leave the branch as is, click the green **"Run workflow"** button.
5. Wait ~1 minute. A green ✓ checkmark = success. A red ✗ = it failed (open it and read the red step; usually a missing secret).

✅ When it's green, the latest xDEO is live at https://xdeo.timothy-walton45.workers.dev

---

## ② Seed the data (so the site isn't empty)

This fills xDEO with real estimates from the House AI analyst so visitors see content, not a blank page. **Do this AFTER step ① succeeds.**

1. Same Actions page: **https://github.com/Timwal78/SqueezeOS/actions**
2. Left sidebar → click **"xdeo-seed"**.
3. Click **"Run workflow"** → green **"Run workflow"**.
4. Wait for the green ✓.

✅ Now https://xdeo.timothy-walton45.workers.dev/share.html shows live estimates and a populated leaderboard. **This is the moment to start advertising.**

---

## ③ List xDEO in the official MCP Registry (gets you found by AI agents)

This publishes xDEO to the directory that Claude/GPT tooling pulls from. One click, no secrets needed.

1. Same Actions page.
2. Left sidebar → click **"xdeo-publish-registry"**.
3. Click **"Run workflow"** → green **"Run workflow"**.
4. Wait for the green ✓.

✅ xDEO is now listed in the MCP Registry. Aggregator sites (mcp.so, Glama, PulseMCP) sync from it automatically over the following days — so one publish spreads to many directories.

---

## The order, simplified

```
ONCE:   Add XDEO_ADMIN_TOKEN secret   (step ⓪)
THEN:   Run xdeo-deploy               (step ①)  ✓ green
THEN:   Run xdeo-seed                 (step ②)  ✓ green   ← now advertise
THEN:   Run xdeo-publish-registry     (step ③)  ✓ green
```

That's the whole launch. After this, you only re-run **xdeo-deploy** when code changes, and **xdeo-seed** if you ever want to refresh the demo data.

---

## If something goes red

- Click the failed run → click the red step → read the last few lines.
- 99% of failures are a **missing or misspelled secret**. Check the name is exactly `XDEO_ADMIN_TOKEN` (all caps, underscores).
- Still stuck? Tell me the name of the workflow and what the red line says, and I'll fix it.
