#!/bin/bash
# compute-nodes-startup.sh
# Start cluster services on compute nodes and restore them to active duty
#
# Usage: ./compute-nodes-startup.sh [cluster1|cluster2|all]

set -e

CLUSTER=${1:-all}

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to execute command on rabbit node
exec_on_rabbit() {
    local rabbit_node=$1
    local command=$2
    ssh "$rabbit_node" "$command"
}

# Function to check if we can reach a rabbit node
check_rabbit_connection() {
    local rabbit_node=$1
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$rabbit_node" "exit" 2>/dev/null; then
        log_error "Cannot connect to $rabbit_node via SSH"
        log_error "Please ensure SSH keys are configured and the node is accessible"
        exit 1
    fi
}

startup_compute_nodes() {
    local rabbit_node=$1
    local cluster_num=$2
    local nodes=("${@:3}")
    
    log_info "Starting up compute nodes for Cluster $cluster_num: ${nodes[*]}"
    log_info "Using control node: $rabbit_node"
    
    # Check connection to rabbit node
    check_rabbit_connection "$rabbit_node"
    
    # Step 1: Start cluster services on each compute node
    log_info "Step 1: Starting cluster services on compute nodes..."
    for node in "${nodes[@]}"; do
        log_info "  Starting cluster on $node..."
        if ssh "$node" "pcs cluster start" 2>/dev/null; then
            log_info "  ✓ $node cluster services started"
        else
            log_warn "  Failed to start cluster on $node"
        fi
    done
    
    # Wait for nodes to join
    log_info "Waiting 20 seconds for nodes to join cluster..."
    sleep 20
    
    # Step 2: Verify nodes are online
    log_info "Step 2: Checking node status..."
    exec_on_rabbit "$rabbit_node" "pcs status"
    
    # Step 3: Remove standby mode
    log_info "Step 3: Removing standby mode from compute nodes..."
    for node in "${nodes[@]}"; do
        log_info "  Activating $node..."
        exec_on_rabbit "$rabbit_node" "pcs node unstandby $node"
    done
    
    # Wait for resources to start
    log_info "Waiting 15 seconds for resources to start..."
    sleep 15
    
    # Step 4: Verify final status
    log_info "Step 4: Verifying cluster health..."
    exec_on_rabbit "$rabbit_node" "pcs status"
    echo ""
    exec_on_rabbit "$rabbit_node" "pcs quorum status"
    
    log_info "Startup complete for Cluster $cluster_num compute nodes"
}

# Main execution
case $CLUSTER in
    cluster1|1)
        startup_compute_nodes rabbit-node-1 1 compute-node-2 compute-node-3
        ;;
    cluster2|2)
        startup_compute_nodes rabbit-node-2 2 compute-node-4 compute-node-5
        ;;
    all)
        log_info "Starting up compute nodes for both clusters..."
        startup_compute_nodes rabbit-node-1 1 compute-node-2 compute-node-3
        echo ""
        log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        startup_compute_nodes rabbit-node-2 2 compute-node-4 compute-node-5
        ;;
    *)
        echo "Usage: $0 [cluster1|cluster2|all]"
        echo ""
        echo "  cluster1  - Startup compute-node-2 and compute-node-3 (via rabbit-node-1)"
        echo "  cluster2  - Startup compute-node-4 and compute-node-5 (via rabbit-node-2)"
        echo "  all       - Startup compute nodes for both clusters"
        exit 1
        ;;
esac

log_info "═══════════════════════════════════════════════════════════"
log_info "Compute nodes are now active and participating in the cluster."
log_info "To shutdown again, run: ./compute-nodes-shutdown.sh $CLUSTER"
log_info "═══════════════════════════════════════════════════════════"
