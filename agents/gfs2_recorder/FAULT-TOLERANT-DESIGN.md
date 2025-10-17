# Fault-Tolerant GFS2 Fence Recording

## Overview

The `fence_gfs2_recorder` is designed as a **passive, fault-tolerant recorder** that relies on Pacemaker's cluster state rather than actively monitoring compute nodes. This design is ideal for scenarios where network architecture prevents direct access to compute nodes during fencing events.

## Architecture Principles

### 1. **Passive Recording (Not Active Monitoring)**

The fence agent is **reactive**, not **proactive**:

```text
┌───────────────────────┐        ┌───────────────────────┐        ┌───────────────────────┐
│    Pacemaker/DLM      │───────▶│  fence_gfs2_recorder  │───────▶│       Log Files       │
│    Detects Failure    │        │  (Passive Recorder)   │        │      (Audit Trail)    │
└───────────────────────┘        └───────────────────────┘        └───────────────────────┘
         │                                │                                │
         ▼                                ▼                                ▼
   - Heartbeat loss                 - Records event                  - JSON Lines
   - DLM/GFS2 errors                - Discovers context              - Human readable
   - Split-brain                    - No actual fencing              - Operational logs
   - Resource failure
```

### 2. **Event-Driven Execution**

The recorder is triggered **only when Pacemaker decides to fence**:

1. **Cluster Detects Issue**: Heartbeat loss, resource failure, split-brain
2. **Pacemaker Decision**: Cluster decides node must be fenced
3. **Stonith Initiated**: Primary fence agent (`fence_rabbit-olaf`) performs actual fencing
4. **Recorder Invoked**: `fence_gfs2_recorder` logs the event with GFS2 context
5. **Context Discovery**: Multiple fallback methods to identify affected GFS2 filesystems

## Fault-Tolerant Discovery Methods

The agent uses **3 discovery methods** in order of preference, designed to work even when compute nodes are unreachable:

### Method 1: Kubernetes/NNF CRD Query (Preferred)

```bash
kubectl get nnfstorage -A -o json | jq '.items[] | select(.spec.fileSystemType == "gfs2")'
```

- **Resilient**: Works from rabbit nodes even if compute nodes are down
- **Authoritative**: Direct from Kubernetes resource definitions
- **Fast**: ~100-200ms query time

### Method 2: DLM Status via Pacemaker (Cluster State)

```bash
pcs status resources | grep -E '(dlm|gfs2).*compute-node-X'
```

- **Cluster-Aware**: Uses Pacemaker's knowledge of active resources
- **Works When Fencing**: Available even during node failure scenarios
- **Reliable**: Based on actual cluster resource state

### Method 3: Pacemaker Configuration (Static)

```bash
pcs config show | grep -E '(gfs2|dlm)'
```

- **Configuration-Based**: Reads cluster resource definitions
- **Always Available**: Works regardless of node state
- **Static Context**: Shows configured GFS2 resources

## Why This Design Works

### 1. **Network Architecture Independence**

The fence recorder **doesn't need** direct access to compute nodes because:

- **Pacemaker Triggers**: Cluster state drives fencing decisions
- **Rabbit Node Execution**: Recorder runs on rabbit nodes with cluster access
- **Fallback Methods**: Multiple discovery paths, most don't require compute node access

### 2. **Timing is Perfect**

The recorder is called **after** Pacemaker has already decided to fence:

```text
Timeline:
T0: Node failure occurs (network, hardware, software)
T1: Pacemaker detects failure via heartbeat/resource monitoring
T2: Cluster decides node must be fenced
T3: Primary fence agent (fence_rabbit-olaf) is called
T4: fence_gfs2_recorder is called concurrently or sequentially
T5: Fence recorder discovers GFS2 context and logs event
T6: Actual fencing occurs (compute node powered off/isolated)
```

At **T4/T5**, the compute node may already be unreachable, but the cluster state (**T1-T3**) provides enough context.

### 3. **Cluster State is Authoritative**

The Pacemaker cluster knows:

- Which nodes were running DLM
- Which GFS2 filesystems were mounted
- Resource dependencies and constraints
- Node membership and roles

This information is **more reliable** than trying to query a potentially failing compute node.

## Resilience Features

### 1. **Graceful Degradation**

```python
# Method 1: kubectl (preferred)
kubectl_result = try_kubectl_discovery(compute_node)
if kubectl_result:
    return kubectl_result

# Method 2: DLM status (cluster state)
dlm_result = try_dlm_discovery(compute_node)
if dlm_result:
    return dlm_result

# Method 3: Configuration (static)
pacemaker_result = try_pacemaker_discovery(compute_node)
if pacemaker_result:
    return pacemaker_result

# Graceful fallback
return ["none-detected"]
```

### 2. **Timeout Protection**

- **kubectl**: 5-second timeout
- **pcs commands**: 5-second timeout
- **Non-blocking**: Agent succeeds even if all discovery methods fail

### 3. **Error Handling**

```python
try:
    # Discovery attempt
    result = discovery_method()
    return result
except subprocess.TimeoutExpired:
    logging.debug("Method timed out (expected during fencing)")
except Exception as e:
    logging.debug(f"Method failed: {e}")
return None  # Try next method
```

## Production Benefits

### 1. **Works During Network Partitions**

- **Split-Brain Scenarios**: Recorder can still identify GFS2 context
- **Compute Node Isolation**: Network issues don't block recording
- **Partial Connectivity**: Works even with degraded network paths

### 2. **Reliable Audit Trail**

- **Every Fence Event**: Recorded regardless of compute node reachability
- **Rich Context**: GFS2 filesystem information captured when available
- **Forensic Value**: Helps diagnose cluster issues post-incident

### 3. **No Single Points of Failure**

- **Multiple Discovery Paths**: Not dependent on any single method
- **Cluster Integration**: Leverages existing Pacemaker infrastructure
- **Fallback Options**: Always produces useful log entries

## Configuration Examples

### Standard Deployment (Recommended)

```bash
pcs resource create gfs2-fence-recorder fence_gfs2_recorder \
    op monitor interval=120s timeout=10s \
    op start timeout=10s \
    op stop timeout=10s

# Ensure it runs on rabbit nodes
pcs constraint location gfs2-fence-recorder rule score=1000 \
    hostname eq rabbit-node-1 or hostname eq rabbit-node-2
```

### Discovery Tuning

```bash
# Enable all discovery methods (default)
pcs resource update gfs2-fence-recorder meta env="GFS2_DISCOVERY_ENABLED=true"

# Disable discovery if only basic logging needed
pcs resource update gfs2-fence-recorder meta env="GFS2_DISCOVERY_ENABLED=false"

# Custom kubectl path
pcs resource update gfs2-fence-recorder meta env="KUBECTL_CMD=/usr/local/bin/kubectl"
```

### Log Analysis

```bash
# Monitor fence events in real-time
tail -f /var/log/gfs2-fencing/fence-events-readable.log

# Find all fence events for a specific node
grep "compute-node-3" /var/log/gfs2-fencing/fence-events-readable.log

# Extract GFS2 filesystem involvement
jq -r 'select(.target_node == "compute-node-3") | .gfs2_filesystems[]' \
    /var/log/gfs2-fencing/fence-events-detailed.jsonl

# Count fence events by type
jq -r '.action' /var/log/gfs2-fencing/fence-events-detailed.jsonl | sort | uniq -c
```

## Testing Scenarios

### 1. **Normal Operation**

```bash
# Test with all discovery methods working
env GFS2_DISCOVERY_ENABLED=true /usr/sbin/fence_gfs2_recorder -o reboot -n compute-node-2
# Expected: ["none-detected"] or actual GFS2 names
```

### 2. **Compute Node Unreachable**

```bash
# Test with unreachable target
/usr/sbin/fence_gfs2_recorder -o reboot -n unreachable-node
# Expected: Succeeds, uses cluster state for discovery
```

### 3. **Discovery Disabled**

```bash
# Test with discovery disabled
env GFS2_DISCOVERY_ENABLED=false /usr/sbin/fence_gfs2_recorder -o off -n compute-node-3
# Expected: ["discovery-disabled"]
```

### 4. **Network Partition Simulation**

```bash
# Test with completely unreachable target
/usr/sbin/fence_gfs2_recorder -o reboot -n unreachable-target-test
# Expected: Succeeds using kubectl/DLM/config methods
```

## Summary

The **fault-tolerant design** of `fence_gfs2_recorder` makes it ideal for production environments where:

- ✅ **Network architecture** may prevent direct compute node access
- ✅ **Fencing events** need reliable audit trails
- ✅ **GFS2 context** is important for forensic analysis
- ✅ **Cluster state** is more reliable than individual node queries
- ✅ **High availability** is required for the recording function

The agent **succeeds in its mission** (recording fence events) even when compute nodes are completely unreachable, making it robust for real-world production deployments.
