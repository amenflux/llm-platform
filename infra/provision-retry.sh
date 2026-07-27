#!/usr/bin/env bash
#
# provision-retry.sh
# ------------------
# Oracle "Always Free" A1 (Ampere ARM) capacity in busy regions like
# Frankfurt is frequently exhausted, so `terraform apply` fails with
# "Out of host capacity". This script keeps retrying — cycling through
# all availability domains — until a slot frees up, then exits.
#
# Usage:   bash provision-retry.sh      (run in its own terminal, leave it)
# Stop:    Ctrl+C
#
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"   # the infra dir this script lives in
LOG=/tmp/tf_a1_apply.log

echo "Starting A1 provisioning retry loop from: $DIR"
echo "Cycling availability domains every ~90s until capacity is available."
echo "Press Ctrl+C to stop."
echo

round=0
while true; do
  round=$((round + 1))
  for ad in 1 2 0; do
    echo "=== $(date '+%Y-%m-%d %H:%M:%S')  round $round  AD index $ad ==="
    terraform -chdir="$DIR" apply -auto-approve -var="ad_index=$ad" > "$LOG" 2>&1
    rc=$?

    if [ $rc -eq 0 ]; then
      echo
      echo "############################################################"
      echo "###  SUCCESS — instance provisioned on AD index $ad"
      echo "############################################################"
      terraform -chdir="$DIR" output
      exit 0
    fi

    # If it failed for any reason OTHER than capacity, stop and show it.
    if ! grep -q "Out of host capacity" "$LOG"; then
      echo "!!! Non-capacity error on AD $ad — stopping so you can inspect it:"
      echo
      tail -40 "$LOG"
      exit 2
    fi

    echo "    AD index $ad: out of host capacity."
  done
  echo "--- all availability domains full, sleeping 90s ---"
  echo
  sleep 90
done
