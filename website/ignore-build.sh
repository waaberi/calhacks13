#!/bin/sh
# Vercel uses 0 to skip a deployment and 1 to continue.
# Compare with the last successful deployment, including multi-commit pushes.
previous="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -z "$previous" ]; then
  exit 1
fi

# Missing/shallow history must deploy rather than silently miss an update.
if git diff --quiet "$previous" HEAD -- .; then
  exit 0
else
  exit 1
fi
