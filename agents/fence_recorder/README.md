# fence_recorder - Fence Event Recorder and Coordinator

## Overview

`fence_recorder` is a specialized Pacemaker fence agent that integrates with external systems like external storage. It uses a **request/response pattern** to coordinate fencing operations with external infrastructure, ensuring proper resource cleanup before node fencing occurs.

The agent is designed as a **passive, fault-tolerant recorder** that relies on Pacemaker's cluster state rather than actively monitoring compute nodes. This design is ideal for scenarios where network architecture prevents direct access to compute nodes during fencing events.

## Purpose

This fence agent serves three primary purposes:

1. **External Storage Integration**: Coordinates with external storage systems to safely detach storage resources before fencing
2. **Request/Response Pattern**: Provides asynchronous communication between Pacemaker and external storage systems
3. **Audit Trail**: Creates comprehensive logs of all fencing actions and storage operations

## Architecture Principles

### Passive Recording (Not Active Monitoring)

The fence agent is **reactive**, not **proactive**. It's triggered only when Pacemaker decides to fence a node:

```text
┌───────────────────────┐        ┌───────────────────────┐        ┌───────────────────────┐
│    Pacemaker/DLM      │───────▶│  fence_recorder       │───────▶│       Log Files       │
│    Detects Failure    │        │  (Passive Recorder)   │        │      (Audit Trail)    │
└───────────────────────┘        └───────────────────────┘        └───────────────────────┘
         │                                │                                │
         ▼                                ▼                                ▼
   - Heartbeat loss                 - Records event                  - JSON Lines
   - DLM errors                     - Discovers context              - Human readable
   - Split-brain                    - No actual fencing              - Operational logs
   - Resource failure
```

### Event-Driven Execution

The recorder is triggered **only when Pacemaker decides to fence**:

1. **Cluster Detects Issue**: Heartbeat loss, resource failure, split-brain
2. **Pacemaker Decision**: Cluster decides node must be fenced
3. **Stonith Initiated**: Primary fence agent performs actual fencing
4. **Recorder Invoked**: `fence_recorder` logs the event with filesystem context
5. **Context Discovery**: Multiple fallback methods to identify affected shared filesystems

### Timing and Cluster State

The recorder is called **after** Pacemaker has already decided to fence:

```text
Timeline:
T0: Node failure occurs (network, hardware, software)
T1: Pacemaker detects failure via heartbeat/resource monitoring
T2: Cluster decides node must be fenced
T3: Primary fence agent is called
T4: fence_recorder is called concurrently or sequentially
T5: Fence recorder discovers filesystem context and logs event
T6: Actual fencing occurs (compute node powered off/isolated)
```

At **T4/T5**, the compute node may already be unreachable, but the cluster state (**T1-T3**) provides enough context. The Pacemaker cluster knows which nodes were running DLM, which shared filesystems were mounted, resource dependencies, and node membership—this information is **more reliable** than trying to query a potentially failing compute node.

## Architecture

```text
┌─────────────────────┐
│  Pacemaker/Corosync │
│  (Management Node)  │
└──────────┬──────────┘
           │
           │ Calls fence_recorder
           │
           ▼
┌──────────────────────┐      ┌──────────────────────────────┐
│   fence_recorder     │─────▶│   Request File               │
│   (This Agent)       │      │   /localdisk/fence-recorder/ │
└──────────────────────┘      │   requests/<node>-<uuid>.json│
           │                  └──────────────────────────────┘
           │                                 │
           │ Waits for response              │ External reads request
           │                                 │
           ▼                                 ▼
┌──────────────────────────────┐     ┌──────────────────────────────┐
│   Response File              │◀────│   External Storage           │
│   /localdisk/fence-recorder/ │     │   Reconciler                 │
│   responses/<node>-<uuid>.json│    │   (External Service)         │
└──────────────────────────────┘     └──────────────────────────────┘
           │                                 │
           │ Response indicates success      │ Detaches storage resources
           │                                 │
           ▼                                 ▼
┌──────────────────────┐              ┌──────────────────────────────┐
│      Pacemaker       │              │      External Storage        │
│   (Exit Code 0/1)    │              │      (Safe State)            │
└──────────────────────┘              └──────────────────────────────┘
```

## Features

- **Fault-Tolerant Discovery**: Multiple discovery methods with graceful degradation
- **Network Architecture Independence**: Works even when compute nodes are unreachable
- **Request/Response Pattern**: File-based communication with external storage systems
- **External Storage Integration**: Coordinates with external storage systems for safe storage operations
- **Timeout Handling**: Configurable timeout with fallback on external response delays
- **Structured Logging**:
  - JSON Lines format for machine parsing
  - Human-readable format for manual review
  - Detailed event logging with timestamps and context
- **Pacemaker Integration**: Full OCF compliance with standard fence agent interface
- **Storage Safety**: Ensures proper storage resource detachment before proceeding with fencing

## Fault-Tolerant Discovery Methods

The agent uses **2 discovery methods** in order of preference, designed to work even when compute nodes are unreachable:

### Method 1: DLM Status via Pacemaker (Cluster State)

```bash
pcs status resources | grep -E '(dlm).*compute-node-X'
```

**Advantages**:
- **Cluster-Aware**: Uses Pacemaker's knowledge of active resources
- **Works When Fencing**: Available even during node failure scenarios
- **Reliable**: Based on actual cluster resource state

### Method 2: Pacemaker Configuration (Static)

```bash
pcs config show | grep -E '(shared-fs|dlm)'
```

**Advantages**:
- **Configuration-Based**: Reads cluster resource definitions
- **Always Available**: Works regardless of node state
- **Static Context**: Shows configured shared filesystem resources

### Discovery Resilience Features

**Graceful Degradation**: The agent tries each method in order with automatic fallback:

```python
# Method 1: DLM status (cluster state)
dlm_result = try_dlm_discovery(compute_node)
if dlm_result:
    return dlm_result

# Method 2: Configuration (static)
pacemaker_result = try_pacemaker_discovery(compute_node)
if pacemaker_result:
    return pacemaker_result

# Graceful fallback
return ["none-detected"]
```

**Timeout Protection**:
- **pcs commands**: 5-second timeout per method
- **Non-blocking**: Agent succeeds even if all discovery methods fail

**Error Handling**:
```python
try:
    result = discovery_method()
    return result
except subprocess.TimeoutExpired:
    logging.debug("Method timed out (expected during fencing)")
except Exception as e:
    logging.debug(f"Method failed: {e}")
return None  # Try next method
```

## Why This Design Works

### Network Architecture Independence

The fence recorder **doesn't need** direct access to compute nodes because:
- **Pacemaker Triggers**: Cluster state drives fencing decisions
- **Management Node Execution**: Recorder runs on management nodes with cluster access
- **Fallback Methods**: Multiple discovery paths don't require compute node access

### Production Benefits

**Works During Network Partitions**:
- Split-brain scenarios: Recorder can still identify filesystem context
- Compute node isolation: Network issues don't block recording
- Partial connectivity: Works even with degraded network paths

**Reliable Audit Trail**:
- Every fence event recorded regardless of compute node reachability
- Rich context with shared filesystem information captured when available
- Forensic value for diagnosing cluster issues post-incident

**No Single Points of Failure**:
- Multiple discovery paths not dependent on any single method
- Cluster integration leverages existing Pacemaker infrastructure
- Fallback options always produce useful log entries

## Log Files

The agent creates three log files in `/var/log/fence-recorder/`:

### 1. fence-events.log

Main operational log with all agent activity:

```text
[2025-01-10 14:23:15] [INFO] Fence action requested: reboot for target: compute-node-3
[2025-01-10 14:23:16] [INFO] shared filesystems for compute-node-3: ["storage-1", "storage-4"]
[2025-01-10 14:23:16] [INFO] Recorded fence event: action=reboot, target=compute-node-3, status=initiated
```

### 2. fence-events-readable.log

Concise, grep-friendly format:

```text
[2025-01-10 14:23:16] ACTION=reboot TARGET=compute-node-3 FILESYSTEMS=["storage-1","storage-4"] STATUS=initiated DETAILS=Fence action reboot initiated by Pacemaker
```

### 3. fence-events-detailed.jsonl

JSON Lines format for programmatic analysis:

```json
{"timestamp": "2025-01-10T14:23:16Z", "action": "reboot", "target_node": "compute-node-3", "status": "completed", "details": "Successfully fenced node by deleting 1 shared storage groups", "recorder_node": "mgmt-node-1", "pacemaker_action": "reboot"}
```

## Installation

### 1. Copy Agent to System

```bash
# Copy to fence agents directory
sudo cp fence_recorder /usr/sbin/fence_recorder
sudo chmod 755 /usr/sbin/fence_recorder

# Create log directory
sudo mkdir -p /var/log/fence-recorder
sudo chmod 755 /var/log/fence-recorder
```

### 2. Verify Installation

```bash
# Check metadata
fence_recorder --action metadata

# Test monitor action
fence_recorder --action monitor --hostname compute-node-2
```

## Pacemaker Configuration

### As STONITH Resource (Recommended)

Configure as the primary fence agent for compute nodes:

```bash
# Create STONITH resource for each compute node
pcs stonith create compute-node-2-fence fence_recorder \
    port=compute-node-2 \
    op monitor interval=60s timeout=10s \
    meta env="FENCE_TIMEOUT=90"

pcs stonith create compute-node-3-fence fence_recorder \
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
sudo mkdir -p /localdisk/fence-recorder/{requests,responses}
sudo chmod 755 /localdisk/fence-recorder/{requests,responses}

# If using NFS, ensure proper mounting
# Add to /etc/fstab if needed:
# nfs-server:/path/to/fence-recorder /localdisk/fence-recorder nfs defaults 0 0
```

## Usage Examples

### Manual Testing

```bash
# Test recording a reboot event
fence_recorder --action reboot --hostname compute-node-3

# Test recording a shutdown event
fence_recorder --action off --hostname compute-node-4

# Monitor operation
fence_recorder --action monitor --hostname compute-node-2
```

### Testing Scenarios

**Normal Operation**:
```bash
# Test with all discovery methods working
env FILESYSTEM_DISCOVERY_ENABLED=true /usr/sbin/fence_recorder -o reboot -n compute-node-2
# Expected: ["none-detected"] or actual filesystem names
```

**Compute Node Unreachable**:
```bash
# Test with unreachable target
/usr/sbin/fence_recorder -o reboot -n unreachable-node
# Expected: Succeeds, uses cluster state for discovery
```

**Discovery Disabled**:
```bash
# Test with discovery disabled
env FILESYSTEM_DISCOVERY_ENABLED=false /usr/sbin/fence_recorder -o off -n compute-node-3
# Expected: ["discovery-disabled"]
```

**Network Partition Simulation**:
```bash
# Test with completely unreachable target
/usr/sbin/fence_recorder -o reboot -n unreachable-target-test
# Expected: Succeeds using DLM/config methods
```

### Viewing Logs

```bash
# Tail the main log
tail -f /var/log/fence-recorder/fence-events.log

# View human-readable events
cat /var/log/fence-recorder/fence-events-readable.log

# Parse JSON logs
jq . /var/log/fence-recorder/fence-events-detailed.jsonl

# Find all fence events for a specific node
grep "compute-node-3" /var/log/fence-recorder/fence-events-readable.log

# Get shared filesystems involved in fencing
jq -r 'select(.target_node == "compute-node-3") | .filesystems[]' \
    /var/log/fence-recorder/fence-events-detailed.jsonl
```

## Configuration Options

### Configuration Files

Request/response directories are configured in `config.py` (shared with NNF):

```python
# Directory where fence agents write fence request files
REQUEST_DIR = "/localdisk/fence-recorder/requests"

# Directory where nnf-sos writes fence response files
RESPONSE_DIR = "/localdisk/fence-recorder/responses"
```

### Environment Variables

- `FENCE_TIMEOUT`: Response timeout in seconds (default: `60`)
- `LOG_DIR`: Log directory (default: `/var/log/fence-recorder`)
- `FENCE_LOG`: Main log file (default: `$LOG_DIR/fence-events.log`)
- `FILESYSTEM_DISCOVERY_ENABLED`: Enable/disable filesystem discovery (default: `true`)

### Discovery Tuning

```bash
# Enable all discovery methods (default)
pcs resource update fence-recorder meta env="FILESYSTEM_DISCOVERY_ENABLED=true"

# Disable discovery if only basic logging needed
pcs resource update fence-recorder meta env="FILESYSTEM_DISCOVERY_ENABLED=false"
```

### Command Line Options

- `--log-dir <path>`: Override log directory

### Example with Custom Configuration

```bash
# Use custom timeout and log directory
FENCE_TIMEOUT=120 LOG_DIR=/data/fence-logs \
    fence_recorder --action reboot --hostname compute-node-2

# Override log directory via command line
fence_recorder --action reboot --hostname compute-node-2 --log-dir /custom/logs
```

## Request/Response Pattern

The agent implements a file-based communication pattern with the external system:

### 1. Request Phase

Writes fence request to shared directory:

```bash
# Example request file: /localdisk/fence-recorder/requests/compute-node-3-12345678-1234-1234-1234-123456789abc.json
{
  "request_id": "12345678-1234-1234-1234-123456789abc",
  "timestamp": "2025-01-10T14:23:15Z",
  "action": "reboot",
  "target_node": "compute-node-3",
  "recorder_node": "mgmt-node-1"
}
```

### 2. Response Phase

external storage Reconciler processes request and writes response:

```bash
# Example response file: /localdisk/fence-recorder/responses/compute-node-3-12345678-1234-1234-1234-123456789abc.json
{
  "request_id": "12345678-1234-1234-1234-123456789abc",
  "success": true,
  "message": "Successfully fenced node by deleting 1 shared storage groups",
  "action_performed": "storage_detach",
  "timestamp": "2025-01-10T14:23:16Z"
}
```

## Integration with external Storage

This agent **replaces traditional fence agents** in external environments by coordinating storage operations:

1. **Pacemaker**: Calls `fence_recorder` as the primary STONITH agent
2. **fence_recorder**: Writes fence request and waits for external response
3. **external storage Reconciler**: Detaches NVMe namespaces and responds
4. **Pacemaker**: Receives success/failure based on external response

Example configuration:

```bash
# externally-integrated fence agent (replaces traditional fence agents)
pcs stonith create compute-node-3-fence fence_recorder \
    port=compute-node-3 \
    op monitor interval=60s timeout=10s \
    meta env="FENCE_TIMEOUT=90"

# Ensure request/response directories are available
sudo mkdir -p /localdisk/fence-recorder/{requests,responses}
sudo chmod 755 /localdisk/fence-recorder/{requests,responses}
```

## Testing

### Running the Example External Watcher

For testing and development, you can use the provided `external_fence_watcher.py` script as an example external service that processes fence requests:

```bash
# Manual testing
python3 external_fence_watcher.py

# Or install as a systemd service
sudo cp fence-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fence-watcher.service
sudo systemctl start fence-watcher.service

# Monitor the service
sudo systemctl status fence-watcher.service
sudo journalctl -u fence-watcher.service -f
```

The `fence-watcher.service` file provides a systemd service template that:

- Starts `external_fence_watcher.py` automatically on boot
- Restarts on failure for reliability
- Logs to systemd journal for easy monitoring
- Can be configured via environment variables (see comments in service file)

**Note**: This is a **simple example implementation** for testing. In production, you would replace this with your actual external storage reconciler or fencing coordinator.

## Troubleshooting

### Log Directory Not Writable

```bash
# Check permissions
ls -ld /var/log/fence-recorder

# Fix permissions
sudo chmod 755 /var/log/fence-recorder
sudo chown root:root /var/log/fence-recorder
```

### Request/Response Timeout

If external responses are timing out:

```bash
# Increase fence timeout
pcs resource update compute-node-3-fence \
    meta env="FENCE_TIMEOUT=120"

# Check external system logs (vendor-specific)
journalctl -u external-storage-service --tail=50
```

### Response Directory Issues

```bash
# Check response directory permissions and NFS mount
ls -ld /localdisk/fence-recorder/responses/
mount | grep fence-recorder

# Check for orphaned request files
ls -la /localdisk/fence-recorder/requests/

# Manually clean old requests
find /localdisk/fence-recorder/requests/ -name "*.json" -mtime +1 -delete
```

### external Integration Not Working

```bash
# Test manually
fence_recorder --action monitor --hostname compute-node-3

# Check logs
tail -50 /var/log/fence-recorder/fence-events.log

# Check request/response flow
ls -la /localdisk/fence-recorder/requests/
ls -la /localdisk/fence-recorder/responses/

# Verify external storage system (vendor-specific commands)
# Contact your storage vendor for specific diagnostic commands
```

### Agent Not Running in Pacemaker

```bash
# Check resource status
pcs resource status fence-recorder

# View Pacemaker logs
journalctl -u pacemaker -f

# Check for errors
pcs resource failcount show fence-recorder
```

## Log Rotation

Set up logrotate to manage log file sizes:

```bash
# Create /etc/logrotate.d/fence-recorder
cat <<EOF | sudo tee /etc/logrotate.d/fence-recorder
/var/log/fence-recorder/*.log /var/log/fence-recorder/*.jsonl {
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
- **Filesystem Discovery Overhead**: external queries add ~100-500ms per fence event
- **Log File Size**: Expect ~1KB per fence event
- **Disk I/O**: Minimal impact (append-only writes)

## Security Considerations

- **nnf Access**: Requires cluster-admin nnf config for CRD queries
- **Pacemaker Access**: Requires access to pcs commands for cluster state
- **Log Files**: Contain sensitive cluster topology information
- **File Permissions**: Logs are world-readable by default (0644)

Recommended security measures:

```bash
# Restrict log file permissions
sudo chmod 600 /var/log/fence-recorder/*.log
sudo chmod 600 /var/log/fence-recorder/*.jsonl

# Use SELinux context
sudo semanage fcontext -a -t cluster_var_log_t "/var/log/fence-recorder(/.*)?"
sudo restorecon -Rv /var/log/fence-recorder
```

## Advanced Usage

### Integrate with Monitoring

```bash
# Send alerts on fence events
tail -f /var/log/fence-recorder/fence-events-readable.log | \
    while read line; do
        echo "$line" | mail -s "Fence Event Alert" admin@example.com
    done &
```

### Export to Centralized Logging

```bash
# Ship logs to rsyslog
logger -t fence_recorder -f /var/log/fence-recorder/fence-events-readable.log

# Ship to Elasticsearch
filebeat -e -c filebeat-fence.yml
```

### Create Dashboard

```bash
# Generate fence event statistics
jq -r '[.target_node, .filesystems | length] | @csv' \
    /var/log/fence-recorder/fence-events-detailed.jsonl | \
    sort | uniq -c
```

## Summary

The **fault-tolerant design** of `fence_recorder` makes it ideal for production environments where:

- ✅ **Network architecture** may prevent direct compute node access
- ✅ **Fencing events** need reliable audit trails
- ✅ **Filesystem context** is important for forensic analysis
- ✅ **Cluster state** is more reliable than individual node queries
- ✅ **High availability** is required for the recording function

The agent **succeeds in its mission** (recording fence events) even when compute nodes are completely unreachable, making it robust for real-world production deployments.

## References

- [Request/Response Pattern Documentation](REQUEST-RESPONSE-PATTERN.md)
- [Verification Script Usage](README_VERIFY.md)
- [Pacemaker Fence Agent Development](https://github.com/ClusterLabs/fence-agents)
- [Cluster Configuration Summary](../../pacemaker-cluster-summary.md)
