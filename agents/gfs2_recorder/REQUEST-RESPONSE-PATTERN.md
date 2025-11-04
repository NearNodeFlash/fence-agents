# Fence Request/Response Pattern

## Overview

The `fence_gfs2_recorder` uses a **request/response pattern** to decouple fence event logging from actual fencing operations. This allows you to implement custom fencing logic in a separate component while maintaining full integration with Pacemaker.

## Architecture

```text
┌─────────────────┐         ┌──────────────────────┐             ┌─────────────────────┐
│   Pacemaker     │────────▶│  fence_gfs2_recorder │────────────▶│   Request Files     │
│   (Initiates    │◀────────│   (Records & Waits)  │             │   /localdisk/gfs2-  │
│    Fencing)     │  exit   │                      │             │    fencing/requests │
└─────────────────┘  code   └──────────────────────┘             └─────────────────────┘
                      ▲                   ▲                                │
                      │                   │ reads                          │ watches
                      │                   │ response                       ▼
                      │                   │                      ┌─────────────────────┐
                      │                   │                      │ NnfNodeBlockStorage │
                      │                   │                      │ Reconciler          │
                      │                   │                      │ (Kubernetes)        │
                      │                   │                      └─────────────────────┘
                      │                   │                                │
                      │                   │                                │ writes
                      │                   │                                ▼
                      │         ┌──────────────────────┐         ┌───────────────────────┐
                      └─────────│   Response Files     │◀────────│   Rabbit detaches     │
                       0=success│   /localdisk/gfs2-   │         │   NVMe namespaces     │
                       1=failure│    fencing/responses │         │   from fenced compute │
                                └──────────────────────┘         └───────────────────────┘   
```

## How It Works

### 1. Pacemaker Initiates Fence

When Pacemaker decides a node needs fencing:

```bash
pcs stonith fence compute-node-3
```

### 2. fence_gfs2_recorder Writes Request

The fence agent creates a request file with a unique ID:

**File**: `/localdisk/gfs2-fencing/requests/<uuid>.json`

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-10-20T14:30:00Z",
  "action": "reboot",
  "target_node": "compute-node-3",
  "gfs2_filesystems": ["lustre-fs1", "gfs2-storage"],
  "recorder_node": "rabbit-node-1"
}
```

### 3. NnfNodeBlockStorage Reconciler Processes Request

The NnfNodeBlockStorage Reconciler (Kubernetes controller):

1. Watches the request directory for new fence requests
2. Reads the request file and parses the target node
3. Detaches NVMe namespaces from the fenced compute node
4. Writes a response file confirming the fencing action

### 4. NnfNodeBlockStorage Reconciler Writes Response

**File**: `/localdisk/gfs2-fencing/responses/<uuid>.json`

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "action_performed": "reboot",
  "target_node": "compute-node-3",
  "message": "Successfully fenced node by deleting 1 GFS2 storage groups",
  "timestamp": "2025-10-20T14:30:15Z"
}
```

### 5. fence_gfs2_recorder Returns to Pacemaker

The fence agent:

1. Reads the response file
2. Logs the final result
3. Returns success (exit 0) or failure (exit 1) to Pacemaker

## Implementation Guide

### Step 1: Update fence_gfs2_recorder

The updated version is already configured with request/response support.

### Step 2: Deploy the NnfNodeBlockStorage Reconciler

The NnfNodeBlockStorage Reconciler is part of the NNF (Near Node Flash) software stack and runs as a Kubernetes controller. It automatically:

1. Watches for fence request files in `/localdisk/gfs2-fencing/requests/`
2. Processes fence requests by detaching NVMe namespaces from compute nodes
3. Updates NNFNode resources to reflect fenced status
4. Writes response files to `/localdisk/gfs2-fencing/responses/`

The reconciler is deployed as part of the NNF operator:

```bash
# Verify NNF operator is running
kubectl get pods -n nnf-system

# Check NnfNodeBlockStorage resources
kubectl get nnfnodeblockstorage -A

# Monitor reconciler logs
kubectl logs -n nnf-system -l app=nnf-operator -f
```

### Step 3: Configure NNF Integration

Ensure the NNF software has access to the fence request/response directories:

```bash
# Verify directories exist and are accessible
ls -la /localdisk/gfs2-fencing/
ls -la /localdisk/gfs2-fencing/requests/
ls -la /localdisk/gfs2-fencing/responses/

# Check permissions (should be writable by NNF services)
stat /localdisk/gfs2-fencing/requests/
stat /localdisk/gfs2-fencing/responses/
```

### Step 4: Test the Integration

```bash
# Test fence operation via Pacemaker
pcs stonith fence rabbit-compute-2

# Check request was created and processed
ls -l /localdisk/gfs2-fencing/requests/
ls -l /localdisk/gfs2-fencing/responses/

# Check fence logs
tail /var/log/gfs2-fencing/fence-events-readable.log

# Verify NNFNode status
kubectl get nnfnode rabbit-compute-2 -o yaml

# Check NnfNodeBlockStorage resources
kubectl get nnfnodeblockstorage -A
```

## Configuration

### Configuration Files

The fence agent uses a hybrid approach: critical paths are hardcoded in `config.py` while runtime settings use environment variables:

| Setting | Source | Default | Description |
|---------|--------|---------|-------------|
| `REQUEST_DIR` | `config.py` | `/localdisk/gfs2-fencing/requests` | Directory for fence requests |
| `RESPONSE_DIR` | `config.py` | `/localdisk/gfs2-fencing/responses` | Directory for fence responses |
| `FENCE_TIMEOUT` | Environment | `60` | Timeout in seconds to wait for NNF response |
| `LOG_DIR` | Environment | `/var/log/gfs2-fencing` | Directory for fence event logs |

### config.py

The request/response directories are shared between the fence agent and NNF software, configured in `config.py`:

```python
# Directory where fence agents write fence request files
REQUEST_DIR = "/localdisk/gfs2-fencing/requests"

# Directory where nnf-sos writes fence response files
RESPONSE_DIR = "/localdisk/gfs2-fencing/responses"
```

**Important**: These paths must match between the fence agent and NNF repositories. If you modify `config.py`, ensure both repositories are updated.

### Pacemaker Configuration

Configure timeout and log directory in the stonith resource:

```bash
# Using environment variables (recommended)
pcs resource update compute-node-2-fence-recorder \
    meta env="FENCE_TIMEOUT=90" \
    meta env="LOG_DIR=/custom/log/path"

# Alternative: Using command-line options
pcs resource update compute-node-2-fence-recorder \
    op monitor interval=60s \
    params log-dir="/custom/log/path"
```

**Note**: Environment variables take precedence over command-line options.

## Troubleshooting

### Fence Operation Times Out

```bash
# Check if NNF operator is running
kubectl get pods -n nnf-system -l app=nnf-controller-manager

# Check NNFNode resources
kubectl get nnfnodes -o wide

# Check NNF operator logs
kubectl logs -n nnf-system -l app=nnf-controller-manager --tail=50
```

### Response Not Being Read

```bash
# Check response directory permissions and NFS mount
ls -ld /localdisk/gfs2-fencing/responses/
mount | grep gfs2-fencing

# Check fence_gfs2_recorder logs
tail -f /var/log/gfs2-fencing/fence-events.log

# Check NnfNodeBlockStorage resources
kubectl get nnfnodeblockstorages -o yaml
```

### Increase Timeout

If NNF processing takes longer than 60 seconds:

```bash
pcs resource update compute-node-2-fence-recorder \
    meta env="FENCE_TIMEOUT=120"
```

## Benefits of This Pattern

1. **Separation of Concerns**: GFS2 logging separated from NNF storage management
2. **Kubernetes Integration**: Leverages existing NNF operator infrastructure
3. **Debugging**: Request/response files provide clear audit trail for NNF operations
4. **Storage Safety**: Ensures proper NVMe namespace detachment before node fencing
5. **Testing**: Can simulate operations without affecting actual storage
6. **NNF Awareness**: Native integration with NearNodeFlash storage lifecycle
