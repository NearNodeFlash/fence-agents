# Pacemaker Cluster Configuration Summary
**Date:** October 13, 2025  
**Clusters:** rabbit-node-[1,2] with compute-node-[2,3,4,5]  
**Status:** Fully operational with comprehensive fencing

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

### Rabbit Nodes (rabbit-node-1, rabbit-node-2)
- **Agent:** fence_nnf
- **API Version:** v1alpha8
- **Authentication:** Kubernetes service account with RBAC
- **Certificates:** Updated CA certificates and tokens
- **Resources:** fence_nnf_rabbit-node-1, fence_nnf_rabbit-node-2

### Compute Nodes (compute-node-2,3,4,5)
- **Agent:** fence_ssh
- **Authentication:** Root SSH keys
- **Resources:**
  - compute-node-2-fence (runs on compute-node-3)
  - compute-node-3-fence (runs on compute-node-2)
  - compute-node-4-fence (runs on compute-node-5)
  - compute-node-5-fence (runs on compute-node-4)

### Location Constraints (Anti-Self-Fencing)
```bash
pcs constraint location compute-node-2-fence avoids compute-node-2=INFINITY
pcs constraint location compute-node-3-fence avoids compute-node-3=INFINITY
pcs constraint location compute-node-4-fence avoids compute-node-4=INFINITY
pcs constraint location compute-node-5-fence avoids compute-node-5=INFINITY
```

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
```bash
pcs stonith fence <node-name>  # Test fencing
pcs stonith confirm <node-name>  # Confirm after manual intervention
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

## Troubleshooting Notes
- **DLM Issues:** Ensure stonith-enabled=true before starting DLM
- **SSL Errors:** Update CA certificates and service account tokens
- **Corosync Sync:** Manually copy corosync.conf between cluster nodes
- **Parameter Cleanup:** Remove duplicate fence_nnf parameters
- **SSH Fencing:** Ensure root SSH keys are distributed and authorized_keys updated

## Current Status
✅ Both clusters operational  
✅ DLM running on all nodes  
✅ All fence agents configured and tested  
✅ Location constraints preventing self-fencing  
✅ Configurations synchronized between clusters  
✅ Comprehensive backups created  

## Next Steps
- Monitor cluster health with `pcs status`
- Consider GFS2 filesystem setup if needed
- Regular backup of configurations
- Certificate/token rotation monitoring

## Emergency Contacts/Resources
- Use `pcs cluster stop/start` for maintenance
- `systemctl restart corosync pacemaker` for service restarts
- Backup files available in /root/ and /etc/corosync/ on rabbit nodes</content>
<parameter name="filePath">/Users/anthony.floeder/dev1/fence-agents/pacemaker-cluster-summary.md