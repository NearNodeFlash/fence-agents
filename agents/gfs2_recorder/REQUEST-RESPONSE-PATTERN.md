# Fence Request/Response Pattern

## Overview

The `fence_gfs2_recorder` uses a **request/response pattern** to decouple fence event logging from actual fencing operations. This allows you to implement custom fencing logic in a separate component while maintaining full integration with Pacemaker.

## Architecture

```text
┌─────────────────┐         ┌──────────────────────┐         ┌─────────────────────┐
│   Pacemaker     │────────▶│  fence_gfs2_recorder │────────▶│   Request Files     │
│   (Initiates    │         │   (Records & Waits)  │         │   /var/run/gfs2-    │
│    Fencing)     │         └──────────────────────┘         │    fencing/requests │
└─────────────────┘                    ▲                     └─────────────────────┘
                                       │                                │
                                       │                                │ watches
                                       │                                ▼
                                       │                      ┌─────────────────────┐
                                       │                      │ External Fence      │
                                       │                      │ Component           │
                                       │                      │ (Your Logic)        │
                                       │                      └─────────────────────┘
                                       │                                │
                                       │                                │ writes
                                       │                                ▼
                             ┌──────────────────────┐         ┌─────────────────────┐
                             │   Response Files     │◀────────│   Performs Actual   │
                             │   /var/run/gfs2-     │         │   Fencing Action    │
                             │    fencing/responses │         └─────────────────────┘
                             └──────────────────────┘
```

## How It Works

### 1. Pacemaker Initiates Fence

When Pacemaker decides a node needs fencing:

```bash
pcs stonith fence compute-node-3
```

### 2. fence_gfs2_recorder Writes Request

The fence agent creates a request file with a unique ID:

**File**: `/var/run/gfs2-fencing/requests/<uuid>.json`

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

### 3. External Component Processes Request

Your external fencing component:

1. Watches the request directory
2. Reads the request file
3. Performs the actual fencing operation
4. Writes a response file

### 4. External Component Writes Response

**File**: `/var/run/gfs2-fencing/responses/<uuid>.json`

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "action_performed": "reboot",
  "target_node": "compute-node-3",
  "message": "Fence reboot succeeded for compute-node-3",
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

### Step 2: Deploy the External Fence Component

You have two options:

#### Option A: Use the Simple Polling Script

```bash
# Copy the simple watcher
cp external_fence_watcher_simple.py /usr/local/bin/fence_watcher.py
chmod +x /usr/local/bin/fence_watcher.py

# Edit to add your fencing logic
vim /usr/local/bin/fence_watcher.py
# Replace the perform_fence_action() function with your actual fencing mechanism
```

#### Option B: Create Your Own Watcher

Implement any mechanism that:

1. Watches `/var/run/gfs2-fencing/requests/`
2. Processes `*.json` files
3. Writes response files to `/var/run/gfs2-fencing/responses/`

### Step 3: Run the External Fence Component

#### As a systemd Service (Recommended)

Create `/etc/systemd/system/fence-watcher.service`:

```ini
[Unit]
Description=GFS2 Fence Request Watcher
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/fence_watcher.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=fence-watcher

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable fence-watcher.service
systemctl start fence-watcher.service
systemctl status fence-watcher.service
```

#### As a Background Process (Testing)

```bash
# Run in background
/usr/local/bin/fence_watcher.py &

# Monitor logs
tail -f /var/log/messages | grep fence-watcher
```

### Step 4: Test the Integration

```bash
# Test fence operation
ssh root@rabbit-node-1 "/usr/sbin/fence_gfs2_recorder --action reboot --plug compute-node-3"

# Check request was created and processed
ls -l /var/run/gfs2-fencing/requests/
ls -l /var/run/gfs2-fencing/responses/

# Check logs
tail /var/log/gfs2-fencing/fence-events-readable.log
```

## Configuration

### Environment Variables

The fence agent supports these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUEST_DIR` | `/var/run/gfs2-fencing/requests` | Directory for fence requests |
| `RESPONSE_DIR` | `/var/run/gfs2-fencing/responses` | Directory for fence responses |
| `FENCE_TIMEOUT` | `60` | Timeout in seconds to wait for response |
| `GFS2_DISCOVERY_ENABLED` | `true` | Enable/disable GFS2 discovery |

### Pacemaker Configuration

Set environment variables in the stonith resource:

```bash
pcs resource update compute-node-2-fence-recorder \
    meta env="FENCE_TIMEOUT=90" \
    meta env="GFS2_DISCOVERY_ENABLED=true"
```

## Implementing Your Fencing Logic

Edit the `perform_fence_action()` function in your fence watcher:

### Example 1: Using fence_nnf

```python
def perform_fence_action(action, target_node, gfs2_filesystems):
    """Call fence_nnf to perform actual fencing"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["/usr/sbin/fence_nnf", "--action", action, "--plug", target_node],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        success = result.returncode == 0
        message = f"fence_nnf {'succeeded' if success else 'failed'}: {result.stdout}"
        
        return success, message
        
    except Exception as e:
        return False, f"Fence operation failed: {e}"
```

### Example 2: Using IPMI

```python
def perform_fence_action(action, target_node, gfs2_filesystems):
    """Use IPMI to fence the node"""
    import subprocess
    
    # Map actions to IPMI commands
    ipmi_actions = {
        "on": "power on",
        "off": "power off",
        "reboot": "power cycle"
    }
    
    ipmi_cmd = ipmi_actions.get(action, "power cycle")
    
    try:
        result = subprocess.run(
            ["ipmitool", "-I", "lanplus", "-H", f"{target_node}-ipmi", 
             "-U", "admin", "-P", "password", "chassis", "power", ipmi_cmd],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        success = result.returncode == 0
        return success, f"IPMI {action} {'succeeded' if success else 'failed'}"
        
    except Exception as e:
        return False, f"IPMI operation failed: {e}"
```

### Example 3: Using Cloud Provider API

```python
def perform_fence_action(action, target_node, gfs2_filesystems):
    """Use AWS API to fence EC2 instance"""
    import boto3
    
    try:
        ec2 = boto3.client('ec2')
        
        # Get instance ID from node name
        response = ec2.describe_instances(
            Filters=[{'Name': 'tag:Name', 'Values': [target_node]}]
        )
        
        instance_id = response['Reservations'][0]['Instances'][0]['InstanceId']
        
        if action == "off":
            ec2.stop_instances(InstanceIds=[instance_id])
        elif action == "on":
            ec2.start_instances(InstanceIds=[instance_id])
        elif action == "reboot":
            ec2.reboot_instances(InstanceIds=[instance_id])
        
        return True, f"AWS EC2 {action} initiated for {instance_id}"
        
    except Exception as e:
        return False, f"AWS operation failed: {e}"
```

## Troubleshooting

### Fence Operation Times Out

```bash
# Check if fence watcher is running
systemctl status fence-watcher.service

# Check request directory
ls -l /var/run/gfs2-fencing/requests/

# Check logs
journalctl -u fence-watcher.service -f
```

### Response Not Being Read

```bash
# Check response directory permissions
ls -ld /var/run/gfs2-fencing/responses/

# Check fence_gfs2_recorder logs
tail -f /var/log/gfs2-fencing/fence-events.log
```

### Increase Timeout

If fencing takes longer than 60 seconds:

```bash
pcs resource update compute-node-2-fence-recorder \
    meta env="FENCE_TIMEOUT=120"
```

## Benefits of This Pattern

1. **Separation of Concerns**: Logging logic separated from fencing logic
2. **Flexibility**: Easy to change fencing mechanism without modifying Pacemaker config
3. **Debugging**: Request/response files make troubleshooting easier
4. **Audit Trail**: Complete record of all fence operations
5. **Testing**: Can simulate fencing without actual hardware actions
6. **Custom Logic**: Implement any fencing mechanism (IPMI, cloud, PDU, custom scripts)

## Migration from fence_ssh

To migrate from `fence_ssh` to this pattern:

1. Deploy updated `fence_gfs2_recorder`
2. Deploy fence watcher with your fencing logic
3. Test in development environment
4. Disable old `fence_ssh` resources: `pcs resource disable compute-node-X-fence`
5. Enable new recorder resources: `pcs resource enable compute-node-X-fence-recorder`
6. Monitor logs and verify fencing works
7. Remove old resources when confident: `pcs resource delete compute-node-X-fence`
