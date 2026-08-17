#!/usr/bin/env bash
#
# provision-retry.sh
# ------------------
# Keeps running `terraform apply` until the Always-Free A1 instance
# provisions (i.e. until "Out of host capacity" clears in the region).
# It also retries through transient network/DNS blips, so it can run
# unattended for hours/days. It stops only on a genuine config error.
#
# The first successful pass creates the compartment, network, and IAM;
# only the capacity-gated instance keeps retrying after that.
#
# Usage:   bash provision-retry.sh      (run in its own terminal, leave it)
# Stop:    Ctrl+C
#
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG=/tmp/tf_a1_apply.log

echo "Retry loop starting from: $DIR"
echo "Will retry every ~90s until the instance provisions. Ctrl+C to stop."
echo

round=0
while true; do
  round=$((round + 1))
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')  round $round ==="

  terraform -chdir="$DIR" apply -auto-approve > "$LOG" 2>&1
  rc=$?

  if [ $rc -eq 0 ]; then
    echo
    echo "############################################################"
    echo "###  SUCCESS — instance provisioned"
    echo "############################################################"
    terraform -chdir="$DIR" output
    exit 0
  fi

  # Retry on capacity shortages AND transient network errors.
  if grep -qE "Out of host capacity|dial tcp|no such host|i/o timeout|TLS handshake|connection refused|connection reset|EOF|Client.Timeout" "$LOG"; then
    echo "    transient (capacity or network) — retrying in 90s"
    echo
    sleep 90
    continue
  fi

  # Anything else is a real error worth stopping for.
  echo "!!! Non-transient error — stopping so you can inspect it:"
  echo
  tail -40 "$LOG"
  exit 2
done
