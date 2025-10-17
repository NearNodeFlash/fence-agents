# fence_gfs2_recorder Testing and Deployment Guide

## Quick Start Testing

Before deploying to the cluster, test the fence agent locally:

### 1. Basic Functionality Test

```bash
# Copy the agent to your local bin
sudo cp fence_gfs2_recorder /usr/local/bin/
sudo chmod +x /usr/local/bin/fence_gfs2_recorder

# Test metadata generation
fence_gfs2_recorder --action metadata

# Test monitor action (should create log directory)
fence_gfs2_recorder --action monitor --hostname test-node

# Verify logs were created
ls -la /var/log/gfs2-fencing/
```

### 2. Test GFS2 Discovery

```bash
# Test with kubectl available
fence_gfs2_recorder --action reboot --hostname compute-node-3

# Check what was logged
cat /var/log/gfs2-fencing/fence-events-readable.log

# View detailed JSON
jq . /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

### 3. Test Without kubectl

```bash
# Test discovery fallback
KUBECTL_CMD=/bin/false fence_gfs2_recorder --action reboot --hostname compute-node-3

# Should fall back to SSH-based discovery
grep "kubectl not available" /var/log/gfs2-fencing/fence-events.log
```

## Deployment on Rabbit Nodes

### Option 1: Standalone Resource (Recommended)

This creates a persistent resource that monitors for fencing events:

```bash
# On rabbit-node-1 (Cluster 1)
ssh root@rabbit-node-1

# Copy the agent
sudo cp fence_gfs2_recorder /usr/sbin/fence_gfs2_recorder
sudo chmod 755 /usr/sbin/fence_gfs2_recorder

# Create log directory
sudo mkdir -p /var/log/gfs2-fencing
sudo chmod 755 /var/log/gfs2-fencing

# Create Pacemaker resource
pcs resource create gfs2-fence-recorder-c1 fence_gfs2_recorder \
    op monitor interval=120s timeout=10s \
    op start timeout=10s \
    op stop timeout=10s

# Ensure it runs on rabbit-node-1
pcs constraint location gfs2-fence-recorder-c1 rule score=1000 \
    hostname eq rabbit-node-1

# Enable the resource
pcs resource enable gfs2-fence-recorder-c1
```

Repeat for Cluster 2:

```bash
# On rabbit-node-2 (Cluster 2)
ssh root@rabbit-node-2

# Copy the agent
sudo cp fence_gfs2_recorder /usr/sbin/fence_gfs2_recorder
sudo chmod 755 /usr/sbin/fence_gfs2_recorder

# Create log directory
sudo mkdir -p /var/log/gfs2-fencing
sudo chmod 755 /var/log/gfs2-fencing

# Create Pacemaker resource
pcs resource create gfs2-fence-recorder-c2 fence_gfs2_recorder \
    op monitor interval=120s timeout=10s \
    op start timeout=10s \
    op stop timeout=10s

# Ensure it runs on rabbit-node-2
pcs constraint location gfs2-fence-recorder-c2 rule score=1000 \
    hostname eq rabbit-node-2

# Enable the resource
pcs resource enable gfs2-fence-recorder-c2
```

### Option 2: Integrated with Fence Resources

This approach creates a recorder for each compute node fence agent:

```bash
# On rabbit-node-1
# Create recorder for compute-node-2
pcs resource create compute-node-2-fence-recorder fence_gfs2_recorder \
    hostname=compute-node-2 \
    op monitor interval=120s timeout=10s

# Create recorder for compute-node-3
pcs resource create compute-node-3-fence-recorder fence_gfs2_recorder \
    hostname=compute-node-3 \
    op monitor interval=120s timeout=10s

# Group them with DLM for automatic lifecycle
pcs resource group add dlm-group \
    compute-node-2-fence-recorder \
    compute-node-3-fence-recorder
```

### Option 3: Clone Resource (Multi-Node Recording)

This runs the recorder on all rabbit nodes:

```bash
# Create clone resource
pcs resource create gfs2-fence-recorder fence_gfs2_recorder \
    op monitor interval=120s timeout=10s \
    --clone

# Constrain to rabbit nodes only
pcs constraint location gfs2-fence-recorder-clone rule score=1000 \
    hostname eq rabbit-node-1 or hostname eq rabbit-node-2
```

## Verification

### Check Resource Status

```bash
# View all resources
pcs status

# Check specific recorder resource
pcs resource status gfs2-fence-recorder-c1

# View resource operations
pcs resource op-defaults
```

### Monitor Logs in Real-Time

```bash
# On rabbit-node-1
tail -f /var/log/gfs2-fencing/fence-events.log

# In another terminal, trigger a test fence event
pcs stonith fence compute-node-2

# You should see the event logged immediately
```

### Verify GFS2 Discovery

```bash
# Manually test discovery
ssh root@rabbit-node-1 "fence_gfs2_recorder --action monitor --hostname compute-node-3"

# Check logs for GFS2 filesystems
grep "GFS2 filesystems" /var/log/gfs2-fencing/fence-events.log
```

## Testing Scenarios

### Scenario 1: Simulate Compute Node Failure

```bash
# From your local machine
ssh root@rabbit-node-1

# Put compute node in standby
pcs node standby compute-node-3

# This should trigger fencing - check logs
tail -20 /var/log/gfs2-fencing/fence-events-readable.log

# Bring it back online
pcs node unstandby compute-node-3
```

### Scenario 2: Manual Fence Test

```bash
# Manually trigger fence via stonith
pcs stonith fence compute-node-3

# Check that both happened:
# 1. Actual fence (fence_ssh)
# 2. Event recording (fence_gfs2_recorder)

# View stonith history
pcs stonith history

# View recorder logs
cat /var/log/gfs2-fencing/fence-events-readable.log
```

### Scenario 3: GFS2 Filesystem Access During Fence

```bash
# On compute-node-3, mount a GFS2 filesystem
ssh root@compute-node-3 "mount -t gfs2 /dev/vg_gfs2/lv_shared /mnt/gfs2"

# Now fence the node
pcs stonith fence compute-node-3

# Check logs - should show GFS2 filesystem in use
jq -r '.gfs2_filesystems[]' /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

## Log Analysis

### View All Fence Events

```bash
# Human-readable format
cat /var/log/gfs2-fencing/fence-events-readable.log

# JSON format with pretty printing
jq . /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

### Filter by Compute Node

```bash
# Show all events for compute-node-3
grep "compute-node-3" /var/log/gfs2-fencing/fence-events-readable.log

# JSON query
jq -r 'select(.target_node == "compute-node-3")' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

### Filter by Action Type

```bash
# Show all reboots
grep "ACTION=reboot" /var/log/gfs2-fencing/fence-events-readable.log

# JSON query
jq -r 'select(.action == "reboot")' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

### Count Events by Node

```bash
# Using grep/sort/uniq
grep -o "TARGET=[^ ]*" /var/log/gfs2-fencing/fence-events-readable.log | \
    sort | uniq -c

# Using jq
jq -r '.target_node' /var/log/gfs2-fencing/fence-events-detailed.jsonl | \
    sort | uniq -c
```

### Show GFS2 Filesystems Involved

```bash
# All GFS2 filesystems that have been fenced
jq -r '.gfs2_filesystems[]' /var/log/gfs2-fencing/fence-events-detailed.jsonl | \
    sort -u

# Count fence events per GFS2 filesystem
jq -r '.gfs2_filesystems[]' /var/log/gfs2-fencing/fence-events-detailed.jsonl | \
    sort | uniq -c
```

### Timeline Analysis

```bash
# Show fence events in chronological order
jq -r '[.timestamp, .action, .target_node, .gfs2_filesystems] | @csv' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl

# Events in the last hour
one_hour_ago=$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%S')
jq -r --arg since "$one_hour_ago" \
    'select(.timestamp >= $since) | [.timestamp, .action, .target_node] | @csv' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

## Troubleshooting

### Agent Not Starting

```bash
# Check Pacemaker logs
journalctl -u pacemaker -f

# Check for OCF errors
pcs resource debug-start gfs2-fence-recorder-c1

# Verify agent is executable
ls -l /usr/sbin/fence_gfs2_recorder
```

### No Logs Being Created

```bash
# Check log directory permissions
ls -ld /var/log/gfs2-fencing

# Try manual run
fence_gfs2_recorder --action monitor --hostname test-node

# Check for errors
tail -50 /var/log/gfs2-fencing/fence-events.log
```

### GFS2 Discovery Failing

```bash
# Test kubectl access
kubectl get nnfstorage -A

# Test SSH access to compute nodes
ssh root@compute-node-3 "mount -t gfs2"

# Run with debug
bash -x /usr/sbin/fence_gfs2_recorder --action monitor --hostname compute-node-3
```

### Resource Failing to Monitor

```bash
# Check resource status
pcs resource status gfs2-fence-recorder-c1

# View failcount
pcs resource failcount show gfs2-fence-recorder-c1

# Clear failcount
pcs resource failcount reset gfs2-fence-recorder-c1

# Manually test monitor
fence_gfs2_recorder --action monitor --hostname compute-node-3
echo $?  # Should be 0 for success
```

## Performance Monitoring

### Check Resource Overhead

```bash
# View resource timing
pcs resource op-defaults

# Monitor CPU/memory usage
top -p $(pgrep -f fence_gfs2_recorder)

# Check log file sizes
du -sh /var/log/gfs2-fencing/
```

### Monitor Interval Tuning

```bash
# If logs show too frequent monitoring
pcs resource update gfs2-fence-recorder-c1 \
    op monitor interval=300s  # Change to 5 minutes

# If events are being missed
pcs resource update gfs2-fence-recorder-c1 \
    op monitor interval=60s  # Change to 1 minute
```

## Integration with Monitoring Systems

### Send Alerts on Fence Events

```bash
# Create a monitoring script
cat <<'EOF' > /usr/local/bin/fence-event-monitor.sh
#!/bin/bash
tail -F /var/log/gfs2-fencing/fence-events-readable.log | \
while read -r line; do
    # Extract fields
    action=$(echo "$line" | grep -o "ACTION=[^ ]*" | cut -d= -f2)
    target=$(echo "$line" | grep -o "TARGET=[^ ]*" | cut -d= -f2)
    
    # Send alert (customize for your monitoring system)
    logger -t fence-alert "FENCE EVENT: $action on $target"
    
    # Example: Send to email
    # echo "$line" | mail -s "Fence Alert: $target" admin@example.com
    
    # Example: Send to Slack
    # curl -X POST -H 'Content-type: application/json' \
    #   --data "{\"text\":\"Fence Event: $action on $target\"}" \
    #   https://hooks.slack.com/services/YOUR/WEBHOOK/URL
done
EOF

chmod +x /usr/local/bin/fence-event-monitor.sh

# Run as systemd service
cat <<'EOF' > /etc/systemd/system/fence-event-monitor.service
[Unit]
Description=GFS2 Fence Event Monitor
After=pacemaker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/fence-event-monitor.sh
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fence-event-monitor.service
systemctl start fence-event-monitor.service
```

### Export to Elasticsearch

```bash
# Install filebeat
# Configure filebeat.yml
cat <<'EOF' > /etc/filebeat/inputs.d/gfs2-fence.yml
- type: log
  enabled: true
  paths:
    - /var/log/gfs2-fencing/fence-events-detailed.jsonl
  json.keys_under_root: true
  json.add_error_key: true
  fields:
    type: gfs2-fence-event
  fields_under_root: true
EOF

systemctl restart filebeat
```

## Cleanup and Maintenance

### Log Rotation

```bash
# Verify logrotate is configured
cat /etc/logrotate.d/gfs2-fencing

# Manually rotate logs
logrotate -f /etc/logrotate.d/gfs2-fencing

# Check rotated logs
ls -lh /var/log/gfs2-fencing/
```

### Archive Old Logs

```bash
# Archive logs older than 90 days
find /var/log/gfs2-fencing -name "*.log.*" -mtime +90 -exec gzip {} \;

# Move to archive location
find /var/log/gfs2-fencing -name "*.gz" -mtime +90 \
    -exec mv {} /archive/gfs2-fencing/ \;
```

### Resource Cleanup

```bash
# Remove the recorder resource
pcs resource disable gfs2-fence-recorder-c1
pcs resource delete gfs2-fence-recorder-c1

# Remove log files
sudo rm -rf /var/log/gfs2-fencing/

# Remove agent
sudo rm /usr/sbin/fence_gfs2_recorder
```

## Best Practices

1. **Monitor Log Growth**: Set up alerts when log directory exceeds size threshold
2. **Test Before Production**: Always test in dev environment first
3. **Regular Backups**: Include `/var/log/gfs2-fencing/` in backup policy
4. **Security**: Restrict log file permissions to prevent unauthorized access
5. **Documentation**: Keep runbook for fence event response procedures
6. **Integration**: Connect to centralized logging/monitoring systems
7. **Retention Policy**: Define how long to keep fence event logs
8. **Review Regularly**: Analyze fence events monthly for patterns

## Advanced Configuration

### Custom Log Format

Edit the agent to customize log format:

```bash
# Backup original
cp /usr/sbin/fence_gfs2_recorder /usr/sbin/fence_gfs2_recorder.bak

# Edit record_fence_event() function to customize format
vim /usr/sbin/fence_gfs2_recorder

# Test changes
fence_gfs2_recorder --action monitor --hostname test-node
```

### Multiple Log Destinations

Configure the agent to write to multiple locations:

```bash
# Set up symbolic links
ln -s /var/log/gfs2-fencing/fence-events.log /var/log/messages

# Or configure rsyslog forwarding
cat <<EOF >> /etc/rsyslog.d/gfs2-fence.conf
:programname, isequal, "fence_gfs2_recorder" /var/log/gfs2-fencing/fence-events.log
& stop
EOF

systemctl restart rsyslog
```

## References

- [fence_gfs2_recorder README](./README.md)
- [Pacemaker Cluster Summary](../../pacemaker-cluster-summary.md)
- [GFS2 Fencing Explained](../../GFS2-FENCING-EXPLAINED.md)
- [Fence Monitoring Test Results](../../FENCE-MONITORING-TEST-RESULTS.md)
