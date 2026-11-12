#!/usr/bin/env bash
# Copy the job-scout skill and an example profile into a Hermes home directory.
# This does not create a cron job; scheduling is opt-in (same as Hermes blueprints).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILL_DST="${HERMES_HOME}/skills/job-scout"
DATA_DST="${HERMES_HOME}/job-scout"

mkdir -p "${HERMES_HOME}/skills" "${DATA_DST}"

if [ -e "${SKILL_DST}" ] && [ ! -L "${SKILL_DST}" ]; then
  echo "Replacing existing skill at ${SKILL_DST}"
fi
rm -rf "${SKILL_DST}"
cp -R "${ROOT}/skills/job-scout" "${SKILL_DST}"

if [ -f "${DATA_DST}/profile.yaml" ]; then
  echo "Keeping existing profile at ${DATA_DST}/profile.yaml"
else
  cp "${ROOT}/profile.example.yaml" "${DATA_DST}/profile.yaml"
  # Point the copied profile at the local example resume by default.
  # Users should replace this with their own resume path.
  echo "Wrote ${DATA_DST}/profile.yaml (edit this before relying on a daily run)"
fi

if [ ! -f "${DATA_DST}/resume.example.txt" ]; then
  cp "${ROOT}/resume.example.txt" "${DATA_DST}/resume.example.txt"
fi

# Make the default resume_path work after the copy.
# profile.example.yaml uses resume.example.txt as a relative path.
echo
echo "Installed:"
echo "  skill:   ${SKILL_DST}"
echo "  profile: ${DATA_DST}/profile.yaml"
echo
echo "Next:"
echo "  1. Edit the profile (titles, locations, resume_path, ATS boards)."
echo "  2. Dry-run:"
echo "       python3 ${SKILL_DST}/scripts/job_scout.py \\"
echo "         --profile ${DATA_DST}/profile.yaml --dry-run --verbose"
echo "  3. Schedule (gateway must be running: hermes gateway start):"
echo "       hermes cron create \"0 8 * * *\" \\"
echo "         --name \"Daily job scout\" \\"
echo "         --skill job-scout \\"
echo "         --script ${SKILL_DST}/scripts/job_scout.py \\"
echo "         --deliver origin \\"
echo "         --workdir ${DATA_DST} \\"
echo "         \"Run the daily job-scout scan. Follow the job-scout skill exactly. If the first line is NO_NEW_MATCHES, respond with only [SILENT]. Otherwise send a short digest with title, company, location, one-line reason, and URL. After sending, run the script again with --update-seen.\""
echo
echo "The skill also declares a Hermes blueprint (8:00 AM daily, deliver to origin)."
echo "If Hermes lists it under /suggestions, you can accept it there instead."
