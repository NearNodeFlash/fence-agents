# fence_gfs2_recorder - GFS2 Fencing Event Recorder

## Overview

`fence_gfs2_recorder` is a specialized Pacemaker fence agent that integrates with NearNodeFlash (NNF) storage systems. It uses a **request/response pattern** to coordinate fencing operations with the NNF storage infrastructure, ensuring proper storage detachment before node fencing occurs.

## Purpose

This fence agent serves three primary purposes:

1. **NNF Integration**: Coordinates with NnfNodeBlockStorage Reconciler to safely detach NVMe namespaces before fencing
2. **Request/Response Pattern**: Provides asynchronous communication between Pacemaker and NNF storage systems
3. **Audit Trail**: Creates comprehensive logs of all fencing actions and storage operations

## Architecture

```text
┌─────────────────────┐
│  Pacemaker/Corosync │ 
│   (Rabbit Node)     │
└──────────┬──────────┘
           │
           │ Calls fence_gfs2_recorder
           │
           v
┌──────────────────────┐      ┌─────────────────────────────┐
│  fence_gfs2_recorder │────▶ │   Request File              │
│  (This Agent)        │      │   /localdisk/gfs2-fencing/  │
└──────────────────────┘      │   requests/<uuid>.json      │
           │                  └─────────────────────────────┘
           │                                 │
           │ Waits for response              │ NNF reads request
           │                                 │
           v                                 v
┌─────────────────────────────┐      ┌─────────────────────────────┐
│   Response File             │◀──── │ NnfNodeBlockStorage         │
│   /localdisk/gfs2-fencing/  │      │ Reconciler                  │
│   responses/<uuid>.json     │      │ (Kubernetes Pod)            │
└─────────────────────────────┘      └─────────────────────────────┘
           │                                 │
           │ Response indicates success      │ Detaches NVMe namespaces
           │                                 │
           v                                 v
┌──────────────────────┐               ┌─────────────────────────────┐
│      Pacemaker       │               │      NNF Storage            │
│   (Exit Code 0/1)    │               │   (Safe State)              │
└──────────────────────┘               └─────────────────────────────┘
```

## Features

- **Request/Response Pattern**: File-based communication with NNF storage systems
- **NNF Integration**: Coordinates with NnfNodeBlockStorage Reconciler for safe storage operations
- **Timeout Handling**: Configurable timeout with fallback on NNF response delays
- **Structured Logging**:
  - JSON Lines format for machine parsing
  - Human-readable format for manual review
  - Detailed event logging with timestamps and context
- **Pacemaker Integration**: Full OCF compliance with standard fence agent interface
- **Storage Safety**: Ensures proper NVMe namespace detachment before proceeding with fencing

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
{"timestamp": "2025-01-10T14:23:16Z", "action": "reboot", "target_node": "compute-node-3", "status": "completed", "details": "Successfully fenced node by deleting 1 GFS2 storage groups", "recorder_node": "rabbit-node-1", "pacemaker_action": "reboot"}
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

### As STONITH Resource (Recommended)

Configure as the primary fence agent for compute nodes:

```bash
# Create STONITH resource for each compute node
pcs stonith create compute-node-2-fence fence_gfs2_recorder \
    port=compute-node-2 \
    op monitor interval=60s timeout=10s \
    meta env="FENCE_TIMEOUT=90"

pcs stonith create compute-node-3-fence fence_gfs2_recorder \
    port=compute-node-3 \
    op monitor interval=60s timeout=10s \
    meta env="FENCE_TIMEOUT=90"

# Enable fencing
pcs property set stonith-enabled=true
pcs property set stonith-action=reboot
```

### Directory Setup

Ensure request/response directories exist and are accessible:

```bash
# Create directories
sudo mkdir -p /localdisk/gfs2-fencing/{requests,responses}
sudo chmod 755 /localdisk/gfs2-fencing/{requests,responses}

# If using NFS, ensure proper mounting
# Add to /etc/fstab if needed:
# nfs-server:/path/to/gfs2-fencing /localdisk/gfs2-fencing nfs defaults 0 0
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

### Configuration Files

Request/response directories are configured in `config.py` (shared with NNF):

```python
# Directory where fence agents write fence request files
REQUEST_DIR = "/localdisk/gfs2-fencing/requests"

# Directory where nnf-sos writes fence response files
RESPONSE_DIR = "/localdisk/gfs2-fencing/responses"
```

### Environment Variables

- `FENCE_TIMEOUT`: Response timeout in seconds (default: `60`)
- `LOG_DIR`: Log directory (default: `/var/log/gfs2-fencing`)
- `FENCE_LOG`: Main log file (default: `$LOG_DIR/fence-events.log`)

### Command Line Options

- `--log-dir <path>`: Override log directory

### Example with Custom Configuration

```bash
# Use custom timeout and log directory
FENCE_TIMEOUT=120 LOG_DIR=/data/fence-logs \
    fence_gfs2_recorder --action reboot --hostname compute-node-2

# Override log directory via command line
fence_gfs2_recorder --action reboot --hostname compute-node-2 --log-dir /custom/logs
```

## Request/Response Pattern

The agent implements a file-based communication pattern with the NNF system:

### 1. Request Phase

Writes fence request to shared directory:

```bash
# Example request file: /localdisk/gfs2-fencing/requests/12345678-1234-1234-1234-123456789abc.json
{
  "request_id": "12345678-1234-1234-1234-123456789abc",
  "timestamp": "2025-01-10T14:23:15Z",
  "action": "reboot",
  "target_node": "compute-node-3",
  "recorder_node": "rabbit-node-1"
}
```

### 2. Response Phase

NnfNodeBlockStorage Reconciler processes request and writes response:

```bash
# Example response file: /localdisk/gfs2-fencing/responses/12345678-1234-1234-1234-123456789abc.json
{
  "request_id": "12345678-1234-1234-1234-123456789abc",
  "success": true,
  "message": "Successfully fenced node by deleting 1 GFS2 storage groups",
  "action_performed": "storage_detach",
  "timestamp": "2025-01-10T14:23:16Z"
}
```

## Integration with NNF Storage

This agent **replaces traditional fence agents** in NNF environments by coordinating storage operations:

1. **Pacemaker**: Calls `fence_gfs2_recorder` as the primary STONITH agent
2. **fence_gfs2_recorder**: Writes fence request and waits for NNF response
3. **NnfNodeBlockStorage Reconciler**: Detaches NVMe namespaces and responds
4. **Pacemaker**: Receives success/failure based on NNF response

Example configuration:

```bash
# NNF-integrated fence agent (replaces traditional fence agents)
pcs stonith create compute-node-3-fence fence_gfs2_recorder \
    port=compute-node-3 \
    op monitor interval=60s timeout=10s \
    meta env="FENCE_TIMEOUT=90"

# Ensure request/response directories are available
sudo mkdir -p /localdisk/gfs2-fencing/{requests,responses}
sudo chmod 755 /localdisk/gfs2-fencing/{requests,responses}
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

### Request/Response Timeout

If NNF responses are timing out:

```bash
# Check NNF operator status
kubectl get pods -n nnf-system -l app=nnf-controller-manager

# Check for pending NnfNodeBlockStorage resources
kubectl get nnfnodeblockstorages -A

# Increase fence timeout
pcs resource update compute-node-3-fence \
    meta env="FENCE_TIMEOUT=120"

# Check NNF operator logs
kubectl logs -n nnf-system -l app=nnf-controller-manager --tail=50
```

### Response Directory Issues

```bash
# Check response directory permissions and NFS mount
ls -ld /localdisk/gfs2-fencing/responses/
mount | grep gfs2-fencing

# Check for orphaned request files
ls -la /localdisk/gfs2-fencing/requests/

# Manually clean old requests
find /localdisk/gfs2-fencing/requests/ -name "*.json" -mtime +1 -delete
```

### NNF Integration Not Working

```bash
# Test manually
fence_gfs2_recorder --action monitor --hostname compute-node-3

# Check logs
tail -50 /var/log/gfs2-fencing/fence-events.log

# Verify NNF resources
kubectl get nnfnodes -o wide
kubectl get nnfstorages -A

# Check request/response flow
ls -la /localdisk/gfs2-fencing/requests/
ls -la /localdisk/gfs2-fencing/responses/
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

- **kubectl Access**: Requires cluster-admin kubeconfig for CRD queries
- **Pacemaker Access**: Requires access to pcs commands for cluster state
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

- [Request/Response Pattern Documentation](REQUEST-RESPONSE-PATTERN.md)
- [Verification Script Usage](README_VERIFY.md)
- [Pacemaker Fence Agent Development](https://github.com/ClusterLabs/fence-agents)
- [Cluster Configuration Summary](../../pacemaker-cluster-summary.md)
- [NNF Storage Integration](https://github.com/NearNodeFlash/nnf-sos)
