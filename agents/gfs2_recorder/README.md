# fence_gfs2_recorder - GFS2 Fencing Event Recorder

## Overview

`fence_gfs2_recorder` is a specialized Pacemaker fence agent that runs on rabbit nodes to record GFS2-related fencing events. Unlike traditional fence agents that perform actual node fencing (shutdown/reboot), this agent acts as a **passive recorder** that logs all fencing events with detailed context about GFS2 filesystems.

## Purpose

This fence agent serves two primary purposes:

1. **Audit Trail**: Creates comprehensive logs of all fencing actions for compliance and troubleshooting
2. **GFS2 Context**: Captures which GFS2 filesystems were in use during fencing events

## Architecture

```text
┌─────────────────────┐
│  Pacemaker/Corosync │
│   (Rabbit Node)     │
└──────────┬──────────┘
           │
           ├─────────────────────────────┬─────────────────────────────┐
           │                             │                             │
           v                             v                             v
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│  Primary Fence Agent │    │  fence_gfs2_recorder │    │   DLM/GFS2 Services  │
│   (fence_ssh)        │    │  (This Agent)        │    │                      │
└──────────────────────┘    └──────────────────────┘    └──────────────────────┘
           │                             │                             │
           │                             │                             │
           v                             v                             v
    Performs actual               Records event               Provides context
    node fencing                  to log files                about GFS2 usage
```

## Features

- **GFS2 Discovery**: Automatically detects GFS2 filesystems associated with fenced nodes
- **Multiple Discovery Methods**:
  - Kubernetes/NNF CRD-based (via `kubectl` and NnfStorage resources)
  - SSH-based mount detection (fallback method)
  - DLM status checking
- **Structured Logging**:
  - JSON Lines format for machine parsing
  - Human-readable format for manual review
  - Traditional syslog integration
- **Pacemaker Integration**: Full OCF compliance with standard fence agent interface
- **Zero Impact**: Passive recorder doesn't interfere with actual fencing operations

## Log Files

The agent creates three log files in `/var/log/gfs2-fencing/`:

### 1. fence-events.log

Main operational log with all agent activity:

```text
[2025-01-10 14:23:15] [INFO] Fence action requested: reboot for target: compute-node-3
[2025-01-10 14:23:16] [INFO] GFS2 filesystems for compute-node-3: ["nnf-storage-1", "nnf-storage-4"]
[2025-01-10 14:23:16] [INFO] Recorded fence event: action=reboot, target=compute-node-3, status=initiated
```

### 2. fence-events-readable.log

Concise, grep-friendly format:

```text
[2025-01-10 14:23:16] ACTION=reboot TARGET=compute-node-3 GFS2=["nnf-storage-1","nnf-storage-4"] STATUS=initiated DETAILS=Fence action reboot initiated by Pacemaker
```

### 3. fence-events-detailed.jsonl

JSON Lines format for programmatic analysis:

```json
{"timestamp": "2025-01-10T14:23:16Z", "action": "reboot", "target_node": "compute-node-3", "gfs2_filesystems": ["nnf-storage-1", "nnf-storage-4"], "status": "initiated", "details": "Fence action reboot initiated by Pacemaker", "recorder_node": "rabbit-node-1", "pacemaker_action": "reboot"}
```

## Installation

### 1. Copy Agent to System

```bash
# Copy to fence agents directory
sudo cp fence_gfs2_recorder /usr/sbin/fence_gfs2_recorder
sudo chmod 755 /usr/sbin/fence_gfs2_recorder

# Create log directory
sudo mkdir -p /var/log/gfs2-fencing
sudo chmod 755 /var/log/gfs2-fencing
```

### 2. Verify Installation

```bash
# Check metadata
fence_gfs2_recorder --action metadata

# Test monitor action
fence_gfs2_recorder --action monitor --hostname compute-node-2
```

## Pacemaker Configuration

### As Standalone Resource (Recommended)

Run the recorder as a passive resource that monitors all fencing events:

```bash
# Create the recorder resource
pcs resource create gfs2-fence-recorder fence_gfs2_recorder \
    op monitor interval=120s timeout=10s \
    op start timeout=10s \
    op stop timeout=10s

# Ensure it runs on rabbit nodes
pcs constraint location gfs2-fence-recorder rule score=1000 \
    hostname eq rabbit-node-1 or hostname eq rabbit-node-2

# Start the resource
pcs resource enable gfs2-fence-recorder
```

### As Stonith Notification Handler

Configure Pacemaker to call the recorder during stonith events:

```bash
# Create stonith notification property
pcs property set stonith-action-timeout=60s

# The recorder will automatically be invoked by Pacemaker stonith subsystem
# when any fence action occurs
```

## Usage Examples

### Manual Testing

```bash
# Test recording a reboot event
fence_gfs2_recorder --action reboot --hostname compute-node-3

# Test recording a shutdown event
fence_gfs2_recorder --action off --hostname compute-node-4

# Monitor operation
fence_gfs2_recorder --action monitor --hostname compute-node-2
```

### Viewing Logs

```bash
# Tail the main log
tail -f /var/log/gfs2-fencing/fence-events.log

# View human-readable events
cat /var/log/gfs2-fencing/fence-events-readable.log

# Parse JSON logs
jq . /var/log/gfs2-fencing/fence-events-detailed.jsonl

# Find all fence events for a specific node
grep "compute-node-3" /var/log/gfs2-fencing/fence-events-readable.log

# Get GFS2 filesystems involved in fencing
jq -r 'select(.target_node == "compute-node-3") | .gfs2_filesystems[]' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl
```

## Configuration Options

### Environment Variables

- `KUBECTL_CMD`: Path to kubectl command (default: `kubectl`)
- `LOG_DIR`: Log directory (default: `/var/log/gfs2-fencing`)
- `FENCE_LOG`: Main log file (default: `$LOG_DIR/fence-events.log`)
- `GFS2_DISCOVERY_ENABLED`: Enable GFS2 discovery (default: `true`)

### Command Line Options

- `--log-dir <path>`: Override log directory
- `--no-gfs2-discovery`: Disable automatic GFS2 filesystem discovery

### Example with Custom Configuration

```bash
# Use custom log directory
LOG_DIR=/data/fence-logs fence_gfs2_recorder --action reboot --hostname compute-node-2

# Disable GFS2 discovery
fence_gfs2_recorder --action reboot --hostname compute-node-2 --no-gfs2-discovery
```

## GFS2 Discovery Methods

The agent uses multiple methods to discover GFS2 filesystems:

### Method 1: Kubernetes CRD Query

Queries NnfStorage resources for GFS2 filesystems:

```bash
kubectl get nnfstorage -A -o json | jq '.items[] | select(.spec.fileSystemType == "gfs2")'
```

### Method 2: SSH Mount Query

Falls back to SSH-based mount detection:

```bash
ssh root@compute-node-3 "mount -t gfs2"
```

### Method 3: DLM Status Check

Checks for active DLM resources:

```bash
pcs status resources | grep -i "dlm.*compute-node-3"
```

## Integration with Existing Fencing

This agent **does not replace** your existing fence agents. It works alongside them:

1. **Primary Fence Agent** (e.g., `fence_ssh`): Performs actual node fencing
2. **fence_gfs2_recorder**: Records the event with GFS2 context
3. Both agents run in parallel on rabbit nodes

Example configuration:

```bash
# Primary fence agent (actual fencing)
pcs stonith create compute-node-3-fence fence_ssh \
    port=compute-node-3 \
    identity_file=/root/.ssh/fence-key \
    op monitor interval=60s

# GFS2 recorder (event logging)
pcs resource create gfs2-fence-recorder fence_gfs2_recorder \
    op monitor interval=120s
```

## Troubleshooting

### Log Directory Not Writable

```bash
# Check permissions
ls -ld /var/log/gfs2-fencing

# Fix permissions
sudo chmod 755 /var/log/gfs2-fencing
sudo chown root:root /var/log/gfs2-fencing
```

### kubectl Not Available

If kubectl is not available, the agent will:

1. Log a warning
2. Fall back to SSH-based GFS2 detection
3. Continue operating normally

To enable kubectl support:

```bash
# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Configure kubeconfig
export KUBECONFIG=/etc/kubernetes/admin.conf
```

### GFS2 Discovery Not Working

```bash
# Test manually
fence_gfs2_recorder --action monitor --hostname compute-node-3

# Check logs
tail -50 /var/log/gfs2-fencing/fence-events.log

# Test kubectl access
kubectl get nnfstorage -A

# Test SSH access
ssh root@compute-node-3 "mount -t gfs2"
```

### Agent Not Running in Pacemaker

```bash
# Check resource status
pcs resource status gfs2-fence-recorder

# View Pacemaker logs
journalctl -u pacemaker -f

# Check for errors
pcs resource failcount show gfs2-fence-recorder
```

## Log Rotation

Set up logrotate to manage log file sizes:

```bash
# Create /etc/logrotate.d/gfs2-fencing
cat <<EOF | sudo tee /etc/logrotate.d/gfs2-fencing
/var/log/gfs2-fencing/*.log /var/log/gfs2-fencing/*.jsonl {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
    sharedscripts
}
EOF
```

## Performance Considerations

- **Monitor Interval**: Default 120s is sufficient for most use cases
- **GFS2 Discovery Overhead**: Kubernetes queries add ~100-500ms per fence event
- **Log File Size**: Expect ~1KB per fence event
- **Disk I/O**: Minimal impact (append-only writes)

## Security Considerations

- **SSH Access**: Requires passwordless SSH to compute nodes for mount detection
- **kubectl Access**: Requires cluster-admin kubeconfig for CRD queries
- **Log Files**: Contain sensitive cluster topology information
- **File Permissions**: Logs are world-readable by default (0644)

Recommended security measures:

```bash
# Restrict log file permissions
sudo chmod 600 /var/log/gfs2-fencing/*.log
sudo chmod 600 /var/log/gfs2-fencing/*.jsonl

# Use SELinux context
sudo semanage fcontext -a -t cluster_var_log_t "/var/log/gfs2-fencing(/.*)?"
sudo restorecon -Rv /var/log/gfs2-fencing
```

## Advanced Usage

### Integrate with Monitoring

```bash
# Send alerts on fence events
tail -f /var/log/gfs2-fencing/fence-events-readable.log | \
    while read line; do
        echo "$line" | mail -s "Fence Event Alert" admin@example.com
    done &
```

### Export to Centralized Logging

```bash
# Ship logs to rsyslog
logger -t fence_gfs2 -f /var/log/gfs2-fencing/fence-events-readable.log

# Ship to Elasticsearch
filebeat -e -c filebeat-gfs2.yml
```

### Create Dashboard

```bash
# Generate fence event statistics
jq -r '[.target_node, .gfs2_filesystems | length] | @csv' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl | \
    sort | uniq -c
```

## References

- [Pacemaker Fence Agent Development](https://github.com/ClusterLabs/fence-agents)
- [GFS2 Fencing Requirements](../GFS2-FENCING-EXPLAINED.md)
- [Cluster Configuration Summary](../../pacemaker-cluster-summary.md)
- [NNF GFS2 Integration](https://github.com/NearNodeFlash/nnf-sos)
