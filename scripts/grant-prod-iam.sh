#!/usr/bin/env bash
# Grant the Cloud Functions runtime service account the IAM roles the Conjur3
# callables need on a PRODUCTION Firebase project. Idempotent — re-running an
# existing binding is a no-op, so it's safe to run after every new project or
# whenever a "callable returns INTERNAL with auth/insufficient-permission" shows
# up in the logs.
#
#   PROJECT=<your-project-id> ./scripts/grant-prod-iam.sh
#
# WHY THIS IS NEEDED
#   gen2 Cloud Functions run as the compute service account
#   (<projectNumber>-compute@developer.gserviceaccount.com). On a locked-down
#   project that SA has no Firebase Auth permission. Authorization no longer
#   uses setCustomUserClaims() (memberships in Firestore are the source of
#   truth), but deleteSelf still calls auth.deleteUser(), which needs
#   roles/firebaseauth.admin — without it that callable returns INTERNAL.
#
# This is privileged and acts on prod IAM: run it yourself as a project
# owner / IAM admin. Changes propagate in ~1-2 min; no functions redeploy needed.
set -euo pipefail

PROJECT="${PROJECT:-${FIREBASE_PROJECT:-}}"
if [ -z "$PROJECT" ]; then
  echo "✗ Set PROJECT=<firebase-project-id>   e.g. PROJECT=<your-project-id> $0"
  exit 1
fi

# Default to the project's compute SA unless one is given explicitly.
if [ -n "${FUNCTIONS_SA:-}" ]; then
  SA="$FUNCTIONS_SA"
else
  NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  SA="${NUM}-compute@developer.gserviceaccount.com"
fi

# Roles the functions runtime SA needs. Add more here as new callables require
# new permissions; the binding is idempotent.
ROLES=(
  "roles/firebaseauth.admin"   # auth.deleteUser() (account deletion)
  "roles/datastore.user"       # Firestore reads/writes (usually already present)
)

echo "Project: $PROJECT"
echo "Service account: $SA"
for ROLE in "${ROLES[@]}"; do
  echo "→ ensuring $ROLE"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
done
echo "✓ IAM grants applied (idempotent). Allow ~1-2 min to propagate."
