#!/bin/bash

# Quick Test Script for Request/Response Pattern
# This demonstrates how the fence_gfs2_recorder works with an external fence component

set -e

echo "=== Testing fence_gfs2_recorder Request/Response Pattern ==="
echo

# Start the simple fence watcher in background
echo "1. Starting external fence watcher..."
python3 external_fence_watcher_simple.py &
WATCHER_PID=$!
echo "   Fence watcher PID: $WATCHER_PID"
sleep 2

# Test the fence agent
echo
echo "2. Triggering fence operation..."
./fence_gfs2_recorder.py --action reboot --plug test-compute-node &
FENCE_PID=$!

# Wait a moment
sleep 1

# Show request file
echo
echo "3. Checking request directory..."
ls -lh /localdisk/gfs2-fencing/requests/ || echo "   No requests pending (already processed)"

# Wait for fence to complete
echo
echo "4. Waiting for fence operation to complete..."
wait $FENCE_PID
FENCE_EXIT=$?

echo
echo "5. Fence operation result: exit code $FENCE_EXIT"
if [ $FENCE_EXIT -eq 0 ]; then
    echo "   ✓ Fence operation SUCCEEDED"
else
    echo "   ✗ Fence operation FAILED"
fi

# Show logs
echo
echo "6. Recent fence events:"
tail -3 /var/log/gfs2-fencing/fence-events-readable.log

# Show JSON log
echo
echo "7. Latest fence event (JSON):"
tail -1 /var/log/gfs2-fencing/fence-events-detailed.jsonl | jq .

# Cleanup
echo
echo "8. Stopping fence watcher..."
kill $WATCHER_PID 2>/dev/null || true
wait $WATCHER_PID 2>/dev/null || true

echo
echo "=== Test Complete ==="
