# Compute Node Management Guide

**Date:** October 15, 2025  
**Purpose:** Managing compute nodes independently from rabbit nodes in Pacemaker clusters

## Overview

This guide covers how to cleanly shutdown and restart compute nodes while keeping rabbit nodes and cluster services running. This is useful for:

- Compute node maintenance
- Hardware upgrades on compute nodes
- Testing cluster resilience
- Reducing resource usage during idle periods

## Architecture Considerations

### Cluster Design

- **Rabbit Nodes:** cluster-node-1, rabbit-node-2 (3 votes each)
- **Compute Nodes:** compute-node-2, compute-node-3, compute-node-4, compute-node-5 (1 vote each)
- **Quorum:** Maintained by rabbit nodes alone (6 votes total, quorum = 4)
- **Services:** DLM clone runs on all nodes but can function with rabbit nodes only

### Why This Works

1. **Weighted Quorum:** Rabbit nodes have sufficient votes to maintain quorum
2. **Clone Resources:** DLM can run on subset of nodes
3. **Fence Agent Separation:** Compute nodes can be fenced independently

## Manual Procedure

### Shutdown Compute Nodes

#### Step 1: Put Nodes in Standby

```bash
# From your local machine, connect to rabbit nodes and set standby:

# For Cluster 1:
ssh rabbit-node-1 "pcs node standby compute-node-2"
ssh rabbit-node-1 "pcs node standby compute-node-3"

# For Cluster 2:
ssh rabbit-node-2 "pcs node standby compute-node-4"
ssh rabbit-node-2 "pcs node standby compute-node-5"
```

This gracefully stops all cluster resources on the compute nodes.

#### Step 2: Verify Resource Migration

```bash
# Check Cluster 1 status:
ssh rabbit-node-1 "pcs status"

# Check Cluster 2 status:
ssh rabbit-node-2 "pcs status"

# Wait until you see:
# - Compute nodes in "standby" state
# - DLM clone running only on rabbit nodes
# - All resources stopped on compute nodes
```

#### Step 3: Stop Cluster Services

```bash
# From your local machine, directly stop cluster services on compute nodes:
ssh compute-node-2 "pcs cluster stop"
ssh compute-node-3 "pcs cluster stop"
ssh compute-node-4 "pcs cluster stop"
ssh compute-node-5 "pcs cluster stop"
```

This stops both Pacemaker and Corosync on each compute node.

#### Step 4: Verify Cluster Health

```bash
# Check Cluster 1:
ssh rabbit-node-1 "pcs status"
ssh rabbit-node-1 "pcs quorum status"

# Check Cluster 2:
ssh rabbit-node-2 "pcs status"
ssh rabbit-node-2 "pcs quorum status"

# Expected state:
# - Rabbit nodes: ONLINE
# - Compute nodes: OFFLINE
# - Quorum: Maintained (6 votes from rabbit nodes)
# - DLM: Running on rabbit nodes
```

### Startup Compute Nodes

#### Step 1: Start Cluster Services

```bash
# From your local machine, directly start cluster services on compute nodes:
ssh compute-node-2 "pcs cluster start"
ssh compute-node-3 "pcs cluster start"
ssh compute-node-4 "pcs cluster start"
ssh compute-node-5 "pcs cluster start"
```

#### Step 2: Wait for Nodes to Join

```bash
# Monitor cluster status from your local machine:
ssh rabbit-node-1 "pcs status"  # For Cluster 1
ssh rabbit-node-2 "pcs status"  # For Cluster 2

# Wait for compute nodes to show as ONLINE
# This typically takes 10-20 seconds
```

#### Step 3: Remove Standby Mode

```bash
# From your local machine, remove standby mode:

# For Cluster 1:
ssh rabbit-node-1 "pcs node unstandby compute-node-2"
ssh rabbit-node-1 "pcs node unstandby compute-node-3"

# For Cluster 2:
ssh rabbit-node-2 "pcs node unstandby compute-node-4"
ssh rabbit-node-2 "pcs node unstandby compute-node-5"
```

#### Step 4: Verify Full Operation

```bash
# Check Cluster 1:
ssh rabbit-node-1 "pcs status"
ssh rabbit-node-1 "pcs quorum status"

# Check Cluster 2:
ssh rabbit-node-2 "pcs status"
ssh rabbit-node-2 "pcs quorum status"

# Expected state:
# - All nodes: ONLINE
# - DLM: Running on all nodes
# - Resources: Distributed across all nodes
```

## Automated Scripts

Two scripts are provided for convenience. These scripts can be run from your local machine and will use SSH to execute commands on the rabbit nodes remotely.

### compute-nodes-shutdown.sh

**Purpose:** Cleanly shutdown compute nodes  
**Location:** `/Users/anthony.floeder/dev1/fence-agents/compute-nodes-shutdown.sh`

**Usage:**

```bash
# From your local machine:

# Shutdown Cluster 1 (via rabbit-node-1):
./compute-nodes-shutdown.sh cluster1

# Shutdown Cluster 2 (via rabbit-node-2):
./compute-nodes-shutdown.sh cluster2

# Shutdown both clusters:
./compute-nodes-shutdown.sh all
```

**What it does:**

1. Connects to the appropriate rabbit node via SSH to manage cluster state
2. Puts compute nodes in standby mode (via rabbit node)
3. Waits for resources to migrate
4. Connects directly to compute nodes via SSH to stop cluster services
5. Verifies cluster health (via rabbit node)

**Requirements:**

- SSH access to rabbit nodes (passwordless SSH keys recommended)
- SSH access to compute nodes from your local machine

### compute-nodes-startup.sh

**Purpose:** Start compute nodes and restore to active duty  
**Location:** `/Users/anthony.floeder/dev1/fence-agents/compute-nodes-startup.sh`

**Usage:**

```bash
# From your local machine:

# Startup Cluster 1 (via rabbit-node-1):
./compute-nodes-startup.sh cluster1

# Startup Cluster 2 (via rabbit-node-2):
./compute-nodes-startup.sh cluster2

# Startup both clusters:
./compute-nodes-startup.sh all
```

**What it does:**

1. Connects directly to compute nodes via SSH to start cluster services
2. Waits for nodes to join cluster
3. Connects to rabbit nodes via SSH to remove standby mode
4. Verifies resources start correctly (via rabbit node)

**Requirements:**

- SSH access to rabbit nodes (passwordless SSH keys recommended)
- SSH access to compute nodes from your local machine

### Making Scripts Executable

```bash
chmod +x compute-nodes-shutdown.sh
chmod +x compute-nodes-startup.sh
```

### Setting Up SSH Access

If you don't already have passwordless SSH access to the rabbit nodes:

```bash
# Generate SSH key if you don't have one:
ssh-keygen -t ed25519 -C "your_email@example.com"

# Copy your key to the rabbit nodes:
ssh-copy-id root@rabbit-node-1
ssh-copy-id root@rabbit-node-2

# Test connection:
ssh rabbit-node-1 "hostname"
ssh rabbit-node-2 "hostname"
```

## Troubleshooting

### Issue: Compute Node Won't Stop

**Symptoms:** `pcs cluster stop` hangs or fails

**Solution:**

```bash
# Force stop on the compute node:
ssh compute-node-X "pcs cluster kill"

# Or directly stop services:
ssh compute-node-X "systemctl stop pacemaker corosync"
```

### Issue: Node Stays in Standby After Restart

**Symptoms:** Node is ONLINE but resources don't start

**Solution:**

```bash
# Verify standby status:
pcs status | grep compute-node-X

# Remove standby if needed:
pcs node unstandby compute-node-X
```

### Issue: Quorum Lost

**Symptoms:** Cluster becomes inquorate when compute nodes stop

**Solution:**

```bash
# This shouldn't happen with proper weighting, but if it does:
# Check quorum configuration:
pcs quorum status

# Verify rabbit nodes have 3 votes each:
corosync-quorumtool

# If needed, update quorum configuration (see main summary document)
```

### Issue: DLM Won't Start on Compute Nodes

**Symptoms:** After restart, DLM fails to start on compute nodes

**Solution:**

```bash
# Check DLM resource status:
pcs resource status dlm-clone

# Check for errors:
pcs resource failcount show dlm-clone

# Clear failcount if needed:
pcs resource cleanup dlm-clone
```

### Issue: SSH Connection Fails

**Symptoms:** Cannot SSH to compute nodes

**Solution:**

```bash
# If compute nodes are physically accessible:
# 1. Login to console
# 2. Manually stop cluster:
pcs cluster stop

# From rabbit node, verify SSH keys:
ssh-copy-id root@compute-node-X

# Test connection:
ssh compute-node-X "hostname"
```

## Best Practices

1. **Always use standby mode first** - Don't just kill cluster services
2. **Monitor cluster status** - Watch for unexpected resource moves
3. **Check logs** - Review `/var/log/cluster/corosync.log` for issues
4. **Backup configurations** - Before major changes
5. **Test procedures** - Practice in non-production first
6. **Document changes** - Note any issues or improvements

## Important Notes

### Resource Behavior

- **DLM Clone:** Can run on any subset of nodes
- **Fence Agents:** Compute node fence agents will fail (expected)
- **Location Constraints:** Prevent fence agents from running on their targets

### Quorum Considerations

- Rabbit nodes (6 votes) > Quorum requirement (4 votes)
- Compute nodes can all be offline without losing quorum
- This is by design for this exact use case

### Timing Considerations

- Standby mode: ~5-15 seconds for resources to stop
- Cluster stop: ~5-10 seconds
- Cluster start: ~10-20 seconds for full node join
- Resource start: ~5-15 seconds after unstandby

### Safety Checks

The scripts include:

- SSH connection verification to rabbit nodes
- Cluster membership validation
- Status verification at each step
- Colorized output for visibility

## Emergency Recovery

If something goes wrong and you need to recover:

### Full Cluster Restart

```bash
# Stop everything:
pcs cluster stop --all

# Start rabbit nodes first:
ssh rabbit-node-1 "pcs cluster start"
ssh rabbit-node-2 "pcs cluster start"

# Wait for stabilization (30 seconds)
sleep 30

# Start compute nodes:
for node in compute-node-{2..5}; do
    ssh $node "pcs cluster start"
done

# Remove any standby states:
pcs node unstandby --all
```

### Restore from Backup

```bash
# On rabbit nodes, backups are at:
# /root/pacemaker-config-backup-20251013_145051.tar.bz2 (rabbit-node-1)
# /root/pacemaker-config-backup-20251013_145119.tar.bz2 (rabbit-node-2)

# Stop cluster:
pcs cluster stop --all

# Restore configuration:
pcs config restore /root/pacemaker-config-backup-YYYYMMDD_HHMMSS.tar.bz2

# Restart:
pcs cluster start --all
```

## Related Documentation

- Main cluster configuration: `pacemaker-cluster-summary.md`
- Fence agent setup: See "Fencing Configuration" section
- Corosync configuration: `/etc/corosync/corosync.conf`
- Pacemaker logs: `/var/log/cluster/corosync.log`

## Quick Reference

### Status Checks

```bash
pcs status                    # Overall cluster status
pcs status nodes              # Node status
pcs status resources          # Resource status
pcs quorum status             # Quorum information
pcs node attribute            # Node attributes (including standby)
```

### Node Management

```bash
pcs node standby NODE         # Put node in standby
pcs node unstandby NODE       # Remove standby
pcs cluster stop NODE         # Stop cluster on node
pcs cluster start NODE        # Start cluster on node
pcs cluster kill NODE         # Force kill cluster on node
```

### Common One-Liners

```bash
# Shutdown all compute nodes (Cluster 1) - run from your local machine:
for node in compute-node-{2,3}; do ssh rabbit-node-1 "pcs node standby $node"; done && \
sleep 15 && \
for node in compute-node-{2,3}; do ssh $node "pcs cluster stop"; done

# Startup all compute nodes (Cluster 1) - run from your local machine:
for node in compute-node-{2,3}; do ssh $node "pcs cluster start"; done && \
sleep 20 && \
for node in compute-node-{2,3}; do ssh rabbit-node-1 "pcs node unstandby $node"; done
```
