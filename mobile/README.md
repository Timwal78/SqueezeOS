# Neural_OS Mobile App

Institutional RWA Agentic Infrastructure — Google Play build.

## Screens

| File | Screen |
|------|--------|
| `www/index.html` | Splash / Boot sequence |
| `www/discover.html` | Agent Marketplace |
| `www/agents.html` | Active Neural Clusters |
| `www/wallet.html` | Protocol Wallet |
| `www/subscription.html` | Mesh Capacity / Subscription |
| `www/node-health.html` | Node Health Monitor |
| `www/dashboard.html` | Institutional Core Dashboard |

## Build for Android

```bash
cd mobile
npm install
npx cap add android
npx cap sync
npx cap open android   # opens Android Studio
```

Then in Android Studio: **Build → Generate Signed Bundle/APK** for Google Play upload.

## Requirements

- Node.js 18+
- Android Studio (Ladybug or later)
- JDK 17+
- Android SDK 34 (target), minSdk 24

## Notes

- All screens use Tailwind CSS via CDN — no build step required.
- Fonts (Space Grotesk, Geist, JetBrains Mono) and Material Symbols load from Google CDN; internet permission is required on first launch.
- App ID: `com.neuralOS.institutional`
