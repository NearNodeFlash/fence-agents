# Pacemaker Cluster Configuration Summary

**Date:** October 15, 2025 (Updated)  
**Clusters:** rabbit-node-[1,2] with compute-node-[2,3,4,5]  
**Status:** Fully operational with centralized fencing on rabbit nodes

## Overview

Successfully configured two Pacemaker/corosync clusters with:

- DLM (Distributed Lock Manager) for GFS2 filesystem coordination
- Mixed fencing agents: fence_nnf for rabbit nodes, fence_ssh for compute nodes
- Weighted quorum (rabbit nodes: 3 votes, compute nodes: 1 vote each)
- Location constraints preventing self-fencing
- Synchronized configurations between clusters

## Cluster Architecture

### Cluster 1: rabbit-node-1 + compute-node-[2,3]

### Cluster 2: rabbit-node-2 + compute-node-[4,5]

**Corosync Transport:** udpu with secauth: off  
**Quorum:** Weighted voting enabled  
**STONITH:** Enabled with mixed fence agents

## Fencing Configuration

### Architecture Philosophy

All fence agents for compute nodes run on the **rabbit nodes** (cluster controllers), not on the compute nodes themselves. This provides:

1. **Reliability** - Rabbit nodes are most stable (3 quorum votes each)
2. **Simplicity** - Centralized fencing management
3. **Safety** - Failed compute nodes cannot interfere with their own fencing
4. **Consistency** - Single point of fencing control per cluster

### Rabbit Nodes (rabbit-node-1, rabbit-node-2)

- **Agent:** fence_nnf
- **API Version:** v1alpha8
- **Authentication:** Kubernetes service account with RBAC
- **Certificates:** Updated CA certificates and tokens
- **Resources:** fence_nnf_rabbit-node-1, fence_nnf_rabbit-node-2
- **Location:** Self-fencing prevented via constraints

### Compute Nodes (compute-node-2,3,4,5)

- **Agent:** fence_ssh (bash script at `/usr/sbin/fence_ssh`)
- **Authentication:** Root SSH keys (passwordless)
- **Source Code:** `agents/ssh/fence_ssh` (for reference)
- **Resources:**
  - compute-node-2-fence → **Runs on rabbit-node-1**
  - compute-node-3-fence → **Runs on rabbit-node-1**
  - compute-node-4-fence → **Runs on rabbit-node-2**
  - compute-node-5-fence → **Runs on rabbit-node-2**

### Current Fence Resource Locations

#### Cluster 1 (rabbit-node-1)

```text
rabbit-node-1 (controller, 3 votes)
  ├─ compute-node-2-fence (stonith:fence_ssh) → STARTED on rabbit-node-1
  └─ compute-node-3-fence (stonith:fence_ssh) → STARTED on rabbit-node-1

compute-node-2 (worker, 1 vote)
  └─ Cannot run its own fence resource

compute-node-3 (worker, 1 vote)
  └─ Cannot run its own fence resource
```

#### Cluster 2 (rabbit-node-2)

```text
rabbit-node-2 (controller, 3 votes)
  ├─ compute-node-4-fence (stonith:fence_ssh) → STARTED on rabbit-node-2
  └─ compute-node-5-fence (stonith:fence_ssh) → STARTED on rabbit-node-2

compute-node-4 (worker, 1 vote)
  └─ Cannot run its own fence resource

compute-node-5 (worker, 1 vote)
  └─ Cannot run its own fence resource
```

### Location Constraints

#### Anti-Self-Fencing (Prevents nodes from fencing themselves)

```bash
pcs constraint location compute-node-2-fence avoids compute-node-2=INFINITY
pcs constraint location compute-node-3-fence avoids compute-node-3=INFINITY
pcs constraint location compute-node-4-fence avoids compute-node-4=INFINITY
pcs constraint location compute-node-5-fence avoids compute-node-5=INFINITY
```

#### Rabbit Node Preference (Ensures fence resources run on rabbit nodes)

```bash
# Cluster 1
pcs constraint location compute-node-2-fence prefers rabbit-node-1=1000
pcs constraint location compute-node-3-fence prefers rabbit-node-1=1000

# Cluster 2
pcs constraint location compute-node-4-fence prefers rabbit-node-2=1000
pcs constraint location compute-node-5-fence prefers rabbit-node-2=1000
```

### Fencing Workflows

#### When compute-node-2 Fails

1. Corosync on rabbit-node-1 detects missed heartbeats
2. Pacemaker decides fencing is required
3. compute-node-2-fence resource (running on rabbit-node-1) is triggered
4. rabbit-node-1 executes: `ssh root@compute-node-2 "shutdown -r now"`
5. compute-node-2 reboots (SSH connection closes - expected)
6. Pacemaker confirms fencing successful
7. DLM releases locks, resources can safely migrate/restart

> **Note:** Same process applies for compute-node-3, 4, and 5 with their respective rabbit nodes

#### When Rabbit Node Fails

- Fenced using fence_nnf (Kubernetes-based, out-of-band)
- Triggered by compute nodes via Kubernetes API
- Different mechanism from SSH-based compute fencing

### How fence_ssh Works

**Fence actions:**

```bash
# Reboot action (default)
ssh root@<target-node> "shutdown -r now"

# Off/shutdown action
ssh root@<target-node> "shutdown -h now"
```

**Key features:**

- Uses SSH keys for authentication (no password needed)
- Accepts "connection closed" as success (expected when rebooting)
- 10-second default timeout for actions
- Implements OCF (Open Cluster Framework) resource agent standard
- Network-dependent: requires SSH connectivity to target

## Key Resources

- **DLM Clone Sets:** Active on all nodes for GFS2 support
- **Fence Resources:** 6 total (2 nnf + 4 ssh)
- **Total Resources:** 9 per cluster

## Configuration Backups Created

### Corosync Backups

- `rabbit-node-1`: /etc/corosync/corosync.conf.backup.20251013_145045
- `rabbit-node-2`: /etc/corosync/corosync.conf.backup.20251013_145116

### Pacemaker Backups

- `rabbit-node-1`: /root/pacemaker-config-backup-20251013_145051.tar.bz2
- `rabbit-node-2`: /root/pacemaker-config-backup-20251013_145119.tar.bz2

### XML Exports

- `rabbit-node-1`: /root/pacemaker-config-20251013_145601.xml (latest)

## Critical Commands Used

### Cluster Status Check

```bash
pcs status
pcs quorum status
corosync-quorumtool
```

### Fence Agent Testing

#### Non-Destructive (View Configuration)

```bash
# View fence agent configuration
pcs stonith show
pcs stonith config compute-node-2-fence

# Check fence resource locations
pcs status | grep fence

# View all fencing constraints
pcs constraint config | grep -B1 -A4 'fence'
```

#### Destructive Testing (Actually Fences/Reboots!)

```bash
# WARNING: This will reboot the target node!
pcs stonith fence <node-name>  # Test fencing
pcs stonith confirm <node-name>  # Confirm after manual intervention

# Examples:
ssh rabbit-node-1 "pcs stonith fence compute-node-2"
ssh rabbit-node-2 "pcs stonith fence compute-node-4"
```

#### Verify SSH Connectivity (Prerequisite for fence_ssh)

```bash
# Test from rabbit to compute nodes
ssh rabbit-node-1 "ssh root@compute-node-2 hostname"
ssh rabbit-node-1 "ssh root@compute-node-3 hostname"
ssh rabbit-node-2 "ssh root@compute-node-4 hostname"
ssh rabbit-node-2 "ssh root@compute-node-5 hostname"
```

### Configuration Management

```bash
pcs config show  # View current config
pcs config backup <file>  # Create backup
pcs config restore <file>  # Restore from backup
```

### Resource Management

```bash
pcs resource show  # List all resources
pcs stonith show  # List fence resources
pcs constraint show  # List constraints
```

## Kubernetes Integration (fence_nnf)

- **Service Account:** fence-nnf-sa
- **ClusterRole:** fence-nnf-role with NNF CRD permissions
- **API Calls:** GET/PATCH on nnf.NearNodeFlash.com/v1alpha8
- **Token Location:** /etc/fence_nnf/token
- **CA Certificate:** /etc/fence_nnf/ca.crt

## Troubleshooting

### Common Issues

#### DLM Won't Start

- **Symptom:** DLM resources fail to start
- **Cause:** STONITH not enabled
- **Solution:** `pcs property set stonith-enabled=true`

#### Fence Resource Not on Rabbit Node

- **Symptom:** Fence resource stays on compute node or fails to start
- **Check:** `pcs status` and `pcs constraint config`
- **Solution:**

```bash
# Clear failures and retry
pcs resource cleanup compute-node-2-fence

# Manually move if needed
pcs resource move compute-node-2-fence rabbit-node-1
pcs resource clear compute-node-2-fence  # Clear temporary constraint
```

#### SSH Fencing Fails - Authentication

- **Symptom:** "Permission denied" or "Authentication failed"
- **Check:** `ssh rabbit-node-1 "ssh root@compute-node-2 hostname"`
- **Solution:**

```bash
# Copy SSH keys from rabbit to compute nodes
ssh rabbit-node-1 "ssh-copy-id root@compute-node-2"
ssh rabbit-node-1 "ssh-copy-id root@compute-node-3"
ssh rabbit-node-2 "ssh-copy-id root@compute-node-4"
ssh rabbit-node-2 "ssh-copy-id root@compute-node-5"
```

#### Fencing Timeout

- **Symptom:** "Fence agent did not complete within 20s"
- **Solution:** Increase timeout

```bash
pcs stonith update compute-node-2-fence pcmk_reboot_timeout=120
```

#### SSL/Certificate Errors (fence_nnf)

- **Symptom:** fence_nnf fails with SSL certificate errors
- **Solution:** Update CA certificates and service account tokens in `/etc/fence_nnf/`

#### Corosync Configuration Sync

- **Issue:** Configuration changes not reflected on all nodes
- **Solution:** Manually copy `/etc/corosync/corosync.conf` between cluster nodes and reload

## Current Status (As of October 15, 2025)

✅ Both clusters operational  
✅ DLM running on all nodes  
✅ All fence agents configured and tested  
✅ **All compute fence agents running on rabbit nodes** (centralized fencing)  
✅ Location constraints preventing self-fencing  
✅ Preference constraints ensuring rabbit nodes manage fencing  
✅ Configurations synchronized between clusters  
✅ Comprehensive backups created  
✅ fence_ssh source code documented in `agents/ssh/fence_ssh`

## Maintenance Procedures

### Adding New Compute Nodes

If adding compute-node-6 to cluster 2:

```bash
# Create fence resource
ssh rabbit-node-2 "pcs stonith create compute-node-6-fence fence_ssh \
  pcmk_host_check=static-list \
  pcmk_host_list=compute-node-6 \
  port=compute-node-6"

# Add constraints
ssh rabbit-node-2 "pcs constraint location compute-node-6-fence avoids compute-node-6=INFINITY"
ssh rabbit-node-2 "pcs constraint location compute-node-6-fence prefers rabbit-node-2=1000"

# Ensure SSH keys are set up
ssh rabbit-node-2 "ssh-copy-id root@compute-node-6"
```

### Removing Compute Nodes

```bash
# Remove fence resource (constraints removed automatically)
ssh rabbit-node-1 "pcs stonith delete compute-node-2-fence"
```

### Graceful Compute Node Shutdown

Use the provided scripts (see `COMPUTE-NODE-MANAGEMENT.md`):

```bash
# From your local machine
./compute-nodes-shutdown.sh cluster1  # Shuts down compute-node-[2,3]
./compute-nodes-shutdown.sh cluster2  # Shuts down compute-node-[4,5]

# To restart
./compute-nodes-startup.sh cluster1
./compute-nodes-startup.sh cluster2
```

## Monitoring and Health Checks

### Regular Status Checks

```bash
# Cluster health
ssh rabbit-node-1 "pcs status"
ssh rabbit-node-2 "pcs status"

# Quorum status
ssh rabbit-node-1 "pcs quorum status"

# Fence resource status
ssh rabbit-node-1 "pcs stonith status"

# View fencing history
ssh rabbit-node-1 "pcs stonith history show"

# Check for errors
ssh rabbit-node-1 "journalctl -u pacemaker | grep -i stonith | tail -20"
```

### Best Practices

1. **Test SSH connectivity** before creating fence resources
2. **Set realistic timeouts** - balance between false positives and recovery time
3. **Monitor fencing events** - check pacemaker logs regularly
4. **Use standby mode** for graceful shutdowns (prevents unnecessary fencing)
5. **Test fencing regularly** in maintenance windows
6. **Keep SSH keys synchronized** between rabbit and compute nodes
7. **Document any changes** to fencing topology
8. **Regular backups** of cluster configuration

## Next Steps

- Monitor cluster health with regular `pcs status` checks
- Consider GFS2 filesystem setup if needed (see `GFS2-FENCING-EXPLAINED.md`)
- Regular backup of configurations
- Certificate/token rotation monitoring for fence_nnf

## Related Documentation

- **GFS2-FENCING-EXPLAINED.md** - Why and when fencing occurs with GFS2 filesystems
- **COMPUTE-NODE-MANAGEMENT.md** - Automated scripts for managing compute nodes
- **agents/ssh/fence_ssh** - Source code for fence_ssh agent
- **agents/nnf/fence_nnf.py** - Source code for fence_nnf agent (rabbit nodes)

## Emergency Procedures

### Cluster Maintenance

```bash
# Stop cluster services
pcs cluster stop --all

# Start cluster services
pcs cluster start --all

# Restart services on single node
ssh <node> "systemctl restart corosync pacemaker"
```

### Manual Fencing Recovery

If fencing fails and manual intervention is required:

```bash
# Manually reboot the failed node
ssh <node> "reboot"

# Confirm fencing to Pacemaker
pcs stonith confirm <node-name>
```

### Resource Files

- Backup files available in `/root/` and `/etc/corosync/` on rabbit nodes
- Configuration exports: `/root/pacemaker-config-*.xml`
- Corosync backups: `/etc/corosync/corosync.conf.backup.*`

## Configuration History

- **October 13, 2025**: Initial cluster setup with DLM and mixed fencing
- **October 15, 2025**: Reconfigured all compute fence agents to run on rabbit nodes
  - Added preference constraints (score: 1000) for rabbit nodes
  - Moved compute-node-3-fence from compute-node-2 to rabbit-node-1
  - Moved compute-node-4-fence from compute-node-5 to rabbit-node-2
  - Moved compute-node-5-fence from compute-node-4 to rabbit-node-2
  - Created comprehensive documentation for fencing architecture
  - Updated documentation with centralized fencing workflows
