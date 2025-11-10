# Fence Request/Response Pattern

## Overview

The `fence_recorder` uses a **request/response pattern** to decouple fence event logging from actual fencing operations. This allows you to implement custom fencing logic in a separate component while maintaining full integration with Pacemaker.

## Architecture

```text
┌─────────────────┐         ┌──────────────────────┐          ┌──────────────────────────┐
│   Pacemaker     │────────▶│  fence_recorder      │─────────▶│   Request Files          │
│   (Initiates    │◀────────│  (Records & Waits)   │          │   /localdisk/fence-      │
│    Fencing)     │  exit   │                      │          │   recorder/requests/     │
└─────────────────┘  code   └──────────────────────┘          └──────────────────────────┘
                      ▲                   ▲                              │
                      │                   │ reads                        │ watches
                      │                   │ response                     ▼
                      │                   │                    ┌──────────────────────────┐
                      │                   │                    │ External Storage         │
                      │                   │                    │ Reconciler               │
                      │                   │                    │ (External Service)       │
                      │                   │                    └──────────────────────────┘
                      │                   │                              │
                      │                   │                              │ writes
                      │                   │                              ▼
                      │         ┌──────────────────────┐       ┌──────────────────────────┐
                      └─────────│   Response Files     │◀──────│  Storage Management      │
                       0=success│   /localdisk/fence-  │       │  Detaches NVMe           │
                       1=failure│   recorder/responses/│       │  from Fenced Node        │
                                └──────────────────────┘       └──────────────────────────┘   
```

## How It Works

### 1. Pacemaker Initiates Fence

When Pacemaker decides a node needs fencing:

```bash
pcs stonith fence compute-node-3
```

### 2. fence_recorder Writes Request

The fence agent creates a request file with the target node name and a unique ID:

**File**: `/localdisk/fence-recorder/requests/<node-name>-<uuid>.json`

**Example**: `/localdisk/fence-recorder/requests/compute-node-3-550e8400-e29b-41d4-a716-446655440000.json`

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-10-20T14:30:00Z",
  "action": "reboot",
  "target_node": "compute-node-3",
  "filesystems": ["lustre-fs1", "shared-storage"],
  "recorder_node": "mgmt-node-1"
}
```

### 3. external storage Reconciler Processes Request

The external storage Reconciler (external controller):

1. Watches the request directory for new fence requests
2. Reads the request file and parses the target node
3. Fences the node to prevent further access
4. Writes a response file confirming the fencing action

### 4. external storage Reconciler Writes Response

**File**: `/localdisk/fence-recorder/responses/<node-name>-<uuid>.json`

**Example**: `/localdisk/fence-recorder/responses/compute-node-3-550e8400-e29b-41d4-a716-446655440000.json`

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "action_performed": "reboot",
  "target_node": "compute-node-3",
  "message": "Successfully fenced node by deleting 1 shared storage groups",
  "timestamp": "2025-10-20T14:30:15Z"
}
```

### 5. fence_recorder Returns to Pacemaker

The fence agent:

1. Reads the response file
2. Logs the final result
3. Returns success (exit 0) or failure (exit 1) to Pacemaker

## Implementation Guide

### Step 1: Update fence_recorder

The updated version is already configured with request/response support.

### Step 2: Deploy the external storage Reconciler

The external storage Reconciler is part of the external (Near Node Flash) software stack and runs as a external controller. It automatically:

1. Watches for fence request files in `/localdisk/fence-recorder/requests/`
2. Processes fence requests by detaching NVMe namespaces from compute nodes
3. Updates Node resources to reflect fenced status
4. Writes response files to `/localdisk/fence-recorder/responses/`

The reconciler is deployed as part of the external operator:

```bash
# Verify external operator is running

# Check external storage resources

# Monitor reconciler logs
```

### Step 3: Configure external Integration

Ensure the external software has access to the fence request/response directories:

```bash
# Verify directories exist and are accessible
ls -la /localdisk/fence-recorder/
ls -la /localdisk/fence-recorder/requests/
ls -la /localdisk/fence-recorder/responses/

# Check permissions (should be writable by external services)
stat /localdisk/fence-recorder/requests/
stat /localdisk/fence-recorder/responses/
```

### Step 4: Test the Integration

```bash
# Test fence operation via Pacemaker
pcs stonith fence rabbit-compute-2

# Check request was created and processed
ls -l /localdisk/fence-recorder/requests/
ls -l /localdisk/fence-recorder/responses/

# Check fence logs
tail /var/log/fence-recorder/fence-events-readable.log

# Verify Node status

# Check external storage resources
```

## Configuration

### Configuration Files

The fence agent uses a hybrid approach: critical paths are hardcoded in `config.py` while runtime settings use environment variables:

| Setting | Source | Default | Description |
|---------|--------|---------|-------------|
| `REQUEST_DIR` | `config.py` | `/localdisk/fence-recorder/requests` | Directory for fence requests |
| `RESPONSE_DIR` | `config.py` | `/localdisk/fence-recorder/responses` | Directory for fence responses |
| `FENCE_TIMEOUT` | Environment | `60` | Timeout in seconds to wait for external response |
| `LOG_DIR` | Environment | `/var/log/fence-recorder` | Directory for fence event logs |

### config.py

The request/response directories are shared between the fence agent and external software, configured in `config.py`:

```python
# Directory where fence agents write fence request files
REQUEST_DIR = "/localdisk/fence-recorder/requests"

# Directory where nnf-sos writes fence response files
RESPONSE_DIR = "/localdisk/fence-recorder/responses"
```

**Important**: These paths must match between the fence agent and external repositories. If you modify `config.py`, ensure both repositories are updated.

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
# Check if external operator is running

# Check Node resources

# Check external operator logs
```

### Response Not Being Read

```bash
# Check response directory permissions and NFS mount
ls -ld /localdisk/fence-recorder/responses/
mount | grep fence-recorder

# Check fence_recorder logs
tail -f /var/log/fence-recorder/fence-events.log

# Check external storage resources
```

### Increase Timeout

If external processing takes longer than 60 seconds:

```bash
pcs resource update compute-node-2-fence-recorder \
    meta env="FENCE_TIMEOUT=120"
```

## Benefits of This Pattern

1. **Separation of Concerns**: filesystem logging separated from external storage management
2. **External system Integration**: Leverages existing external operator infrastructure
3. **Debugging**: Request/response files provide clear audit trail for external operations
4. **Storage Safety**: Ensures proper NVMe namespace detachment before node fencing
5. **Testing**: Can simulate operations without affecting actual storage
6. **NNF Awareness**: Native integration with external system storage lifecycle
