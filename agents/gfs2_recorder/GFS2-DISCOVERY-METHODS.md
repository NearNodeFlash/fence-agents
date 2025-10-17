# GFS2 Filesystem Name Discovery Methods

## Do You Need Kubernetes?

**Short Answer: NO** - You can discover GFS2 filesystem names without Kubernetes using traditional Linux/cluster tools.

**However**: Kubernetes provides additional context and more accurate discovery in NNF environments.

## Method Comparison

### Method 1: Direct Mount Query (No Kubernetes Required)

**How it works**: Query the `mount` command to see currently mounted GFS2 filesystems.

```bash
# On the target compute node
ssh root@compute-node-3 "mount -t gfs2"
```

**Example Output**:

```text
/dev/mapper/vg_gfs2-lv_shared on /mnt/gfs2_shared type gfs2 (rw,noatime,nodiratime)
cluster1:my_gfs2_vol on /data/myapp type gfs2 (rw,relatime)
```

**GFS2 Filesystem Names Extracted**:

- `cluster1:my_gfs2_vol` (from the device name)
- Can also be extracted from `/mnt/gfs2_shared` (mount point)

**Parsing**:

```bash
# Get GFS2 device names
mount -t gfs2 | awk '{print $1}'

# Output:
# /dev/mapper/vg_gfs2-lv_shared
# cluster1:my_gfs2_vol
```

**Advantages**:

- ✅ No dependencies (standard Linux tools)
- ✅ Accurate for currently mounted filesystems
- ✅ Fast (no API calls)
- ✅ Works on any Linux system with GFS2

**Disadvantages**:

- ❌ Only shows currently mounted filesystems
- ❌ Misses recently unmounted filesystems
- ❌ Doesn't work if node is down/unreachable
- ❌ No storage topology context

### Method 2: DLM Lock Query (No Kubernetes Required)

**How it works**: Query the Distributed Lock Manager to see which GFS2 filesystems have active locks.

```bash
# Check DLM status
dlm_tool ls

# Or via Pacemaker
pcs status resources | grep -i dlm
```

**Example Output**:

```text
dlm lockspaces
name          id
gfs2_shared   0x12345678
my_gfs2_vol   0x87654321
```

**GFS2 Filesystem Names**: The lockspace names correspond to GFS2 filesystem names.

**Alternative - Check lock files**:

```bash
ls -la /sys/kernel/dlm/
# Output shows lockspace directories, each is a GFS2 filesystem
```

**Advantages**:

- ✅ Shows filesystems with active cluster locks
- ✅ No Kubernetes dependency
- ✅ Works even if filesystem temporarily unmounted
- ✅ Cluster-aware

**Disadvantages**:

- ❌ Only shows filesystems with current DLM activity
- ❌ May miss idle filesystems
- ❌ Requires DLM to be running

### Method 3: /proc/mounts Query (No Kubernetes Required)

**How it works**: Read `/proc/mounts` directly for GFS2 entries.

```bash
grep gfs2 /proc/mounts
```

**Example Output**:

```text
cluster1:my_gfs2_vol /data/myapp gfs2 rw,relatime,quota=off 0 0
```

**Parsing**:

```bash
grep gfs2 /proc/mounts | awk '{print $1}'
# Output: cluster1:my_gfs2_vol
```

**Advantages**:

- ✅ Direct kernel interface (very fast)
- ✅ No external commands needed
- ✅ Reliable

**Disadvantages**:

- ❌ Same as Method 1 (current mounts only)

### Method 4: Kubernetes CRD Query (Requires Kubernetes)

**How it works**: Query NNF (NearNodeFlash) Kubernetes Custom Resource Definitions.

```bash
kubectl get nnfstorage -A -o json | \
  jq -r '.items[] | select(.spec.fileSystemType == "gfs2") | .metadata.name'
```

**Example Output**:

```text
nnf-storage-compute-node-3-gfs2-1
nnf-storage-compute-node-3-gfs2-2
```

**Detailed Query with Node Association**:

```bash
kubectl get nnfstorage -A -o json | \
  jq -r '.items[] | 
    select(.spec.fileSystemType == "gfs2") |
    {
      name: .metadata.name,
      namespace: .metadata.namespace,
      nodes: [.spec.allocationSets[].nodes[]],
      capacity: .spec.capacity
    }'
```

**Advantages**:

- ✅ Shows all GFS2 filesystems in the cluster (mounted or not)
- ✅ Provides storage topology (which nodes have access)
- ✅ Historical data (filesystems that existed)
- ✅ Additional metadata (capacity, labels, etc.)
- ✅ Works even if compute node is down

**Disadvantages**:

- ❌ Requires Kubernetes/NNF deployment
- ❌ Requires kubectl and kubeconfig access
- ❌ API call overhead (~100-500ms)
- ❌ More complex parsing

### Method 5: GFS2 Superblock Query (No Kubernetes Required)

**How it works**: Read GFS2 filesystem name directly from the superblock.

```bash
# Using gfs2_tool (if available)
gfs2_tool sb /dev/mapper/vg_gfs2-lv_shared all | grep "sb_locktable"

# Or using tune2fs-like tools
gfs2_edit -p sb /dev/mapper/vg_gfs2-lv_shared | grep lock_table
```

**Example Output**:

```text
sb_locktable = cluster1:my_gfs2_vol
```

**Advantages**:

- ✅ Most authoritative (direct from filesystem metadata)
- ✅ Works for unmounted filesystems
- ✅ No cluster dependency

**Disadvantages**:

- ❌ Requires block device access
- ❌ Requires GFS2 tools installed
- ❌ Must know which block devices to check
- ❌ Slow for many devices

### Method 6: Pacemaker Resource Configuration (No Kubernetes Required)

**How it works**: Parse Pacemaker configuration to find GFS2 filesystem resources.

```bash
pcs config show | grep -A 10 "Filesystem"
```

**Example Output**:

```text
Resource: fs_gfs2_shared (class=ocf provider=heartbeat type=Filesystem)
  Attributes: device=/dev/mapper/vg_gfs2-lv_shared directory=/mnt/gfs2_shared fstype=gfs2
```

**Parsing**:

```bash
pcs resource show | grep -i gfs2
```

**Advantages**:

- ✅ Shows intended GFS2 configuration
- ✅ No Kubernetes dependency
- ✅ Cluster context

**Disadvantages**:

- ❌ Only shows Pacemaker-managed filesystems
- ❌ May not reflect current state (if resource stopped)
- ❌ Requires Pacemaker access

## Recommended Approach for fence_gfs2_recorder

### Hybrid Strategy (Current Implementation)

The fence agent uses a **fallback chain**:

1. **Try Kubernetes first** (if kubectl available):

   ```bash
   kubectl get nnfstorage -A -o json | jq ...
   ```

2. **Fall back to SSH mount query**:

   ```bash
   ssh root@compute-node "mount -t gfs2 | awk '{print \$1}'"
   ```

3. **Fall back to DLM check**:

   ```bash
   pcs status resources | grep -i "dlm.*$compute_node"
   ```

### Why This Approach?

**Primary (Kubernetes)**:

- Most comprehensive in NNF environments
- Provides storage topology
- Works when node is down

**Fallback (SSH/mount)**:

- Works without Kubernetes
- Simple and reliable
- Fast

**Tertiary (DLM)**:

- Confirms GFS2 activity
- Minimal context but better than nothing

## Code Implementation Without Kubernetes

Here's how to implement GFS2 discovery using **only traditional Linux tools**:

```bash
#!/bin/bash

discover_gfs2_no_kubernetes() {
    local compute_node="$1"
    local gfs2_list=()
    
    # Method 1: Query mounted GFS2 filesystems via SSH
    echo "Checking mounted GFS2 filesystems..." >&2
    local mounted_gfs2
    mounted_gfs2=$(ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no \
        root@"$compute_node" \
        "mount -t gfs2 2>/dev/null | awk '{print \$1}'" 2>/dev/null)
    
    if [[ -n "$mounted_gfs2" ]]; then
        while IFS= read -r fs; do
            [[ -n "$fs" ]] && gfs2_list+=("$fs")
        done <<< "$mounted_gfs2"
    fi
    
    # Method 2: Check DLM lockspaces (if node is a DLM member)
    echo "Checking DLM lockspaces..." >&2
    local dlm_lockspaces
    dlm_lockspaces=$(ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no \
        root@"$compute_node" \
        "dlm_tool ls 2>/dev/null | tail -n +2 | awk '{print \$1}'" 2>/dev/null)
    
    if [[ -n "$dlm_lockspaces" ]]; then
        while IFS= read -r lockspace; do
            [[ -n "$lockspace" ]] && gfs2_list+=("$lockspace")
        done <<< "$dlm_lockspaces"
    fi
    
    # Method 3: Query Pacemaker for GFS2 resources on this node
    echo "Checking Pacemaker GFS2 resources..." >&2
    local pcs_gfs2
    pcs_gfs2=$(pcs resource status 2>/dev/null | \
        grep -i "filesystem.*gfs2.*$compute_node" | \
        awk '{print $2}' | tr -d '()')
    
    if [[ -n "$pcs_gfs2" ]]; then
        while IFS= read -r fs; do
            [[ -n "$fs" ]] && gfs2_list+=("$fs")
        done <<< "$pcs_gfs2"
    fi
    
    # Remove duplicates and output as JSON array
    if [[ ${#gfs2_list[@]} -eq 0 ]]; then
        echo '["none-detected"]'
    else
        # Convert to JSON array (remove duplicates)
        printf '%s\n' "${gfs2_list[@]}" | sort -u | \
            jq -R -s -c 'split("\n") | map(select(length > 0))'
    fi
}

# Usage
discover_gfs2_no_kubernetes "compute-node-3"
```

**Output Examples**:

```json
["cluster1:my_gfs2_vol", "/dev/mapper/vg_gfs2-lv_shared"]
```

Or if nothing found:

```json
["none-detected"]
```

## Simplified Agent Without Kubernetes

Here's a **Kubernetes-free version** of the fence agent:

```bash
#!/bin/bash
# fence_gfs2_recorder - Simple version without Kubernetes

discover_gfs2_filesystems() {
    local compute_node="$1"
    
    # Try SSH mount query
    local gfs2_mounts
    gfs2_mounts=$(ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no \
        root@"$compute_node" \
        "mount -t gfs2 2>/dev/null | awk '{print \$1}'" 2>/dev/null | \
        jq -R -s -c 'split("\n") | map(select(length > 0))' || echo '["ssh-failed"]')
    
    if [[ "$gfs2_mounts" != '[]' && "$gfs2_mounts" != '["ssh-failed"]' ]]; then
        echo "$gfs2_mounts"
        return 0
    fi
    
    # Fallback: Check DLM
    if pcs status resources 2>/dev/null | grep -qi "dlm.*$compute_node"; then
        echo '["gfs2-probable-via-dlm"]'
    else
        echo '["none-detected"]'
    fi
}

# This works without any Kubernetes installation
fence_action() {
    local action="$1"
    local target="$2"
    
    # Discover GFS2 without Kubernetes
    local gfs2_list=$(discover_gfs2_filesystems "$target")
    
    # Log the event
    echo "[$(date)] ACTION=$action TARGET=$target GFS2=$gfs2_list" >> /var/log/gfs2-fencing.log
}
```

## Performance Comparison

| Method | Speed | Accuracy | Dependencies | When Node Down |
|--------|-------|----------|--------------|----------------|
| SSH mount | Fast (50ms) | Current only | SSH | ❌ Fails |
| DLM query | Fast (100ms) | Active locks | DLM | ✅ Works |
| Kubernetes | Medium (200ms) | Complete | kubectl/k8s | ✅ Works |
| Superblock | Slow (500ms) | Authoritative | GFS2 tools | ✅ Works |
| Pacemaker | Fast (100ms) | Configured | Pacemaker | ✅ Works |

## Real-World Examples

### Example 1: GFS2 Mounted as cluster:fsname

```bash
# On compute-node
$ mount -t gfs2
cluster1:shared_data on /mnt/shared type gfs2 (rw,relatime)

# GFS2 filesystem name: "cluster1:shared_data"
# Extracted: cluster1:shared_data
```

### Example 2: GFS2 Mounted as Device

```bash
# On compute-node
$ mount -t gfs2
/dev/mapper/mpatha-gfs2_vol on /data type gfs2 (rw,noatime)

# GFS2 filesystem name: from device
# Extracted: /dev/mapper/mpatha-gfs2_vol
# 
# To get the actual GFS2 name, check superblock:
$ gfs2_tool sb /dev/mapper/mpatha-gfs2_vol all | grep sb_locktable
sb_locktable = cluster1:production_data

# Real GFS2 name: "cluster1:production_data"
```

### Example 3: DLM Lockspace Names

```bash
$ dlm_tool ls
dlm lockspaces
name                id
production_data     0x6b4d7b2f
scratch_data        0x4a2c1d3e

# GFS2 filesystem names:
# - production_data
# - scratch_data
```

## Conclusion

### Kubernetes is NOT Required

You can discover GFS2 filesystem names using:

- `mount -t gfs2` (for mounted filesystems)
- `dlm_tool ls` (for active lockspaces)
- `/proc/mounts` (kernel interface)
- `gfs2_tool` (superblock inspection)
- Pacemaker configuration

### Kubernetes Adds Value

In NNF environments, Kubernetes provides:

- **Complete inventory** (all GFS2 filesystems, not just mounted)
- **Storage topology** (which nodes have access)
- **Historical data** (filesystems that were recently active)
- **Additional metadata** (capacity, labels, ownership)

### Recommendation

For **maximum compatibility**, use the hybrid approach in the current `fence_gfs2_recorder`:

1. Try Kubernetes (best data)
2. Fall back to SSH/mount (works everywhere)
3. Check DLM as last resort (confirms GFS2 activity)

This ensures the agent works:

- ✅ In pure Pacemaker/GFS2 environments (no Kubernetes)
- ✅ In NNF/Kubernetes environments (enhanced discovery)
- ✅ When compute nodes are down (Kubernetes has the data)
- ✅ When Kubernetes is unavailable (traditional methods work)

### For Your Environment

If you **don't have Kubernetes** or **don't want the dependency**, you can simplify the agent to use only:

```bash
ssh root@compute-node "mount -t gfs2 | awk '{print \$1}'"
```

This gives you the GFS2 filesystem names without any Kubernetes infrastructure.
