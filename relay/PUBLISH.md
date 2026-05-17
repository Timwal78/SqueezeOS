# Publishing @relay/mcp-paywall to npm from Your Phone

No terminal required. Three steps, all from GitHub.com.

---

## Step 1: Add NPM_TOKEN to GitHub Secrets (30 seconds)

1. Go to [npmjs.com](https://npmjs.com) → log in → tap your avatar → **Access Tokens** → **Generate New Token** → **Classic** → **Automation**
2. Copy the token (it starts with `npm_`)
3. Go to [github.com/timwal78/squeezeos](https://github.com/timwal78/squeezeos) → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
4. Name: `NPM_TOKEN`, Value: paste the token → **Add secret**

---

## Step 2: Push a version tag to trigger publish (10 seconds)

Go to [github.com/timwal78/squeezeos](https://github.com/timwal78/squeezeos) → **Releases** → **Create a new release**

- **Tag:** `mcp-paywall/v0.1.0`
- **Target:** `claude/relay-agent-commerce-BYvie` (the current branch)
- **Title:** `@relay/mcp-paywall v0.1.0 — Zero-custody XRPL x402 payments for MCP`
- **Description:** copy the highlights from the npm README (zero-custody guarantees, one-wrapper-function setup, RLUSD micropayments, auto-pay agent side)
- Click **Publish release**

The GitHub Action `.github/workflows/publish-mcp-paywall.yml` runs automatically and publishes to npm.

You can watch it live under the **Actions** tab — look for the `publish-mcp-paywall` workflow run.

---

## Step 3: Submit to awesome-mcp-servers (2 taps)

After the package shows as live on [npmjs.com/package/@relay/mcp-paywall](https://www.npmjs.com/package/@relay/mcp-paywall), submit to the community directories below.

### Primary directory — punkpeye/awesome-mcp-servers

1. On your phone, go to this exact URL:
   `https://github.com/punkpeye/awesome-mcp-servers/edit/main/README.md`
2. GitHub will automatically fork the repo for you
3. Find the section with payment or monetization tools (or add a new `## Monetization` heading if none exists)
4. Add this line:

```
- [@relay/mcp-paywall](https://www.npmjs.com/package/@relay/mcp-paywall) - Zero-custody x402 RLUSD micropayments for MCP tool servers. Agents auto-pay on 402; servers verify on XRPL. One wrapper function, no payment infra.
```

5. Tap **Propose changes** → **Create pull request**
6. Use this PR title: `feat: add @relay/mcp-paywall — x402 RLUSD micropayments for MCP`

---

## Other Directories to Submit To (same flow)

Repeat the same edit-and-propose-PR flow on each of these:

- `https://github.com/wong2/awesome-mcp-servers/edit/main/README.md`
- `https://github.com/appcypher/awesome-mcp-servers/edit/main/README.md`

The listing text is the same for all three.

---

## npm version bump for future releases

When you are back at a terminal:

```bash
cd relay/mcp-paywall
npm version patch  # bumps 0.1.0 → 0.1.1
git push && git push --tags  # triggers the publish workflow automatically
```

The tag format `mcp-paywall/v*` is what the GitHub Action watches, so the workflow fires on every push that matches.
