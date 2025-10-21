#!/bin/bash
# compute-nodes-shutdown.sh
# Cleanly shutdown cluster services on compute nodes while keeping rabbit nodes running
#
# Usage: ./compute-nodes-shutdown.sh [cluster1|cluster2|all]

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

shutdown_compute_nodes() {
    local rabbit_node=$1
    local cluster_num=$2
    local nodes=("${@:3}")
    
    log_info "Shutting down compute nodes for Cluster $cluster_num: ${nodes[*]}"
    log_info "Using control node: $rabbit_node"
    
    # Check connection to rabbit node
    check_rabbit_connection "$rabbit_node"
    
    # Step 1: Put nodes in standby
    log_info "Step 1: Putting compute nodes in standby mode..."
    for node in "${nodes[@]}"; do
        log_info "  Setting $node to standby..."
        exec_on_rabbit "$rabbit_node" "pcs node standby $node"
    done
    
    # Wait for resources to migrate
    log_info "Waiting 15 seconds for resources to migrate..."
    sleep 15
    
    # Step 2: Verify resource status
    log_info "Step 2: Checking resource status..."
    exec_on_rabbit "$rabbit_node" "pcs status"
    
    # Step 3: Stop cluster services on each compute node
    log_info "Step 3: Stopping cluster services on compute nodes..."
    for node in "${nodes[@]}"; do
        log_info "  Stopping cluster on $node..."
        if ssh "$node" "pcs cluster stop" 2>/dev/null; then
            log_info "  ✓ $node cluster services stopped"
        else
            log_warn "  Failed to stop cluster on $node (may already be stopped)"
        fi
    done
    
    # Step 4: Verify final status
    log_info "Step 4: Verifying cluster health..."
    sleep 5
    exec_on_rabbit "$rabbit_node" "pcs status"
    echo ""
    exec_on_rabbit "$rabbit_node" "pcs quorum status"
    
    log_info "Shutdown complete for Cluster $cluster_num compute nodes"
}

# Main execution
case $CLUSTER in
    cluster1|1)
        shutdown_compute_nodes rabbit-node-1 1 compute-node-2 compute-node-3
        ;;
    cluster2|2)
        shutdown_compute_nodes rabbit-node-2 2 compute-node-4 compute-node-5
        ;;
    all)
        log_info "Shutting down compute nodes for both clusters..."
        shutdown_compute_nodes rabbit-node-1 1 compute-node-2 compute-node-3
        echo ""
        log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        shutdown_compute_nodes rabbit-node-2 2 compute-node-4 compute-node-5
        ;;
    *)
        echo "Usage: $0 [cluster1|cluster2|all]"
        echo ""
        echo "  cluster1  - Shutdown compute-node-2 and compute-node-3 (via rabbit-node-1)"
        echo "  cluster2  - Shutdown compute-node-4 and compute-node-5 (via rabbit-node-2)"
        echo "  all       - Shutdown compute nodes for both clusters"
        exit 1
        ;;
esac

log_info "═══════════════════════════════════════════════════════════"
log_info "Compute nodes are now offline. Rabbit nodes continue running."
log_info "To restart, run: ./compute-nodes-startup.sh $CLUSTER"
log_info "═══════════════════════════════════════════════════════════"
