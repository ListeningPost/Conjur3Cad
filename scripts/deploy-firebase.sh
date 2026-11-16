#!/usr/bin/env bash
# Deploy the Firebase side: Firestore rules + indexes, Cloud Functions, and the
# Next.js web app (Hosting via web frameworks). Requires `firebase login` and a
# Blaze-plan project.
#
#   FIREBASE_PROJECT=<your-project-id> ./scripts/deploy-firebase.sh
#
# IMPORTANT — why this script quarantines .env.local:
#   The Hosting step runs `next build`, and Next loads `.env.local` at HIGHER
#   precedence than `.env.production`. Dev machines keep emulator/demo settings
#   in .env.local (NEXT_PUBLIC_USE_EMULATORS=true, demo-conjur3 project), so an
#   unguarded deploy bakes emulator mode + the wrong project into the prod
#   bundle — the live app then probes 127.0.0.1 (tripping the browser's
#   local-network prompt) and talks to the demo backend. To make a deploy from
#   any dev machine safe, we move the dev-only env files aside for the build and
#   always restore them afterward, plus sanity-check .env.production up front.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${FIREBASE_PROJECT:-}"
PROJ_FLAG=""
[ -n "$PROJECT" ] && PROJ_FLAG="--project $PROJECT"

if ! firebase projects:list >/dev/null 2>&1; then
  echo "Not logged in. Run: firebase login   (and set FIREBASE_PROJECT=…)"; exit 1
fi

# --- Quarantine dev-only env files so they can't leak into the prod build -----
# Next loads each of these ABOVE .env.production during `next build`; on a dev
# machine they hold emulator/demo values. Move them aside; ALWAYS restore them
# (trap EXIT fires on success, error, or Ctrl-C).
QUARANTINE=()
restore_env() {
  local f
  for f in "${QUARANTINE[@]:-}"; do
    [ -n "$f" ] || continue
    if [ -f "$f.deploybak" ]; then
      mv -f "$f.deploybak" "$f"
      echo "↩  restored $f"
    fi
  done
}
trap restore_env EXIT
for f in .env.local .env.development.local .env.production.local; do
  if [ -f "$f" ]; then
    mv -f "$f" "$f.deploybak"
    QUARANTINE+=("$f")
    echo "→ quarantined $f for the prod build"
  fi
done

# --- Fail fast if the effective prod env is wrong -----------------------------
if [ ! -f .env.production ]; then
  echo "✗ .env.production missing — refusing to deploy."; exit 1
fi
if grep -qE '^[[:space:]]*NEXT_PUBLIC_USE_EMULATORS=true' .env.production; then
  echo "✗ .env.production has NEXT_PUBLIC_USE_EMULATORS=true — refusing to ship emulator mode to prod."; exit 1
fi
if grep -q 'demo-conjur3' .env.production; then
  echo "✗ .env.production references the demo project (demo-conjur3) — refusing to deploy."; exit 1
fi

echo "→ Building Cloud Functions…"
npm --prefix functions run build

# Clear Next's build cache so no previously-built (possibly emulator-flavored)
# chunk survives into this release.
rm -rf .next .firebase/*/hosting 2>/dev/null || true

echo "→ Deploying Firestore rules + indexes, Functions, and Hosting (Next app)…"
echo "  (Hosting builds the Next app from .env.production; dev env files are"
echo "   quarantined for the duration of this build.)"
firebase deploy \
  --only firestore:rules,firestore:indexes,functions,hosting \
  $PROJ_FLAG

echo "✓ Firebase deploy complete."
echo "  Reminder: the Stripe extension is installed separately —"
echo "    firebase ext:install stripe/firestore-stripe-payments $PROJ_FLAG"
