#!/usr/bin/env python3
"""
YouTube OAuth Refresh Token Generator
Run this once on your local machine to get the refresh token for GitHub Actions.

Usage:
  python video/get_youtube_token.py --client-id YOUR_ID --client-secret YOUR_SECRET
"""

import sys
import json
import argparse
import webbrowser
import urllib.request
import urllib.parse

SCOPE    = "https://www.googleapis.com/auth/youtube.upload"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client-id",     required=True)
    p.add_argument("--client-secret", required=True)
    args = p.parse_args()

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={args.client_id}"
        f"&redirect_uri={REDIRECT}"
        f"&scope={urllib.parse.quote(SCOPE)}"
        "&response_type=code"
        "&access_type=offline"
        "&prompt=consent"
    )

    print("\n── Step 1: Opening browser for Google sign-in ──────────────────")
    print(f"  URL: {auth_url}\n")
    webbrowser.open(auth_url)

    code = input("── Step 2: Paste the code Google gave you here → ").strip()

    body = urllib.parse.urlencode({
        "client_id":     args.client_id,
        "client_secret": args.client_secret,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  REDIRECT,
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read())

    refresh = resp.get("refresh_token", "")
    if not refresh:
        print("\nERROR: no refresh_token in response:", resp)
        sys.exit(1)

    print("\n── Done! Add these 3 secrets to GitHub Actions ─────────────────")
    print(f"  YOUTUBE_CLIENT_ID      = {args.client_id}")
    print(f"  YOUTUBE_CLIENT_SECRET  = {args.client_secret}")
    print(f"  YOUTUBE_REFRESH_TOKEN  = {refresh}")
    print("\nGitHub → your repo → Settings → Secrets → Actions → New secret")

if __name__ == "__main__":
    main()
