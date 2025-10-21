#!/bin/bash
# Trigger Fencing Test - Kill Corosync Method
# This simulates a node crash by killing corosync without cleanup

echo "=== Fencing Test: Kill Corosync on compute-node-3 ==="
echo ""
echo "This will:"
echo "1. Monitor fence logs in real-time"
echo "2. Kill corosync process on compute-node-3 (simulates crash)"
echo "3. Pacemaker will detect node loss and trigger fencing"
echo ""

# Start monitoring logs
echo "Starting log monitoring..."
ssh rabbit-node-1 "tail -f /var/log/gfs2-fencing/fence-events-readable.log" &
TAIL_PID=$!

sleep 2

echo ""
echo "Killing corosync on compute-node-3..."
ssh compute-node-3 "sudo killall -9 corosync"

echo ""
echo "Waiting for Pacemaker to detect failure and trigger fencing..."
echo "(This typically takes 10-30 seconds)"
echo ""
echo "Watch the logs above for fence events..."
echo "Press Ctrl+C to stop monitoring"

# Wait for user to stop
wait $TAIL_PID
