#!/usr/libexec/platform-python -tt

# Copyright 2025 Hewlett Packard Enterprise Development LP
# Other additional copyright holders may be indicated within.
#
# The entirety of this work is licensed under the Apache License,
# Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.
#
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# GFS2 Fencing Recorder Agent
#
# This fence agent runs on rabbit nodes to record GFS2 fencing events.
# It integrates with Pacemaker/Corosync and logs all fencing actions
# to a file, including the compute node being fenced and the GFS2
# filesystem involved (if determinable).

import sys
import os
import json
import logging
import subprocess
import socket
import time
import uuid
from datetime import datetime, timezone
import atexit

sys.path.append("/usr/share/fence")
try:
    from fencing import *  # type: ignore
    from fencing import fail_usage, run_delay, all_opt, check_input, process_input, show_docs, atexit_handler  # type: ignore
except ImportError:
    # Fallback definitions for testing/development environments
    all_opt = {}
    def check_input(device_opt, options): return options if options else {}
    def process_input(device_opt): return {}
    def show_docs(options, docs): print(f"Docs: {docs.get('shortdesc', 'GFS2 Fence Recorder')}")
    def run_delay(options): pass
    def fail_usage(message): sys.exit(1)
    def atexit_handler(): pass

# Configuration
KUBECTL_CMD = os.environ.get("KUBECTL_CMD", "kubectl")
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/gfs2-fencing")
FENCE_LOG = os.environ.get("FENCE_LOG", os.path.join(LOG_DIR, "fence-events.log"))
REQUEST_DIR = os.environ.get("REQUEST_DIR", "/localdisk/gfs2-fencing/requests")
RESPONSE_DIR = os.environ.get("RESPONSE_DIR", "/localdisk/gfs2-fencing/responses")
FENCE_TIMEOUT = int(os.environ.get("FENCE_TIMEOUT", "60"))  # Default 60 second timeout
GFS2_DISCOVERY_ENABLED = os.environ.get("GFS2_DISCOVERY_ENABLED", "true").lower() == "true"

# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REQUEST_DIR, exist_ok=True)
os.makedirs(RESPONSE_DIR, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(FENCE_LOG),
        logging.StreamHandler(sys.stderr)
    ]
)


def run_command(cmd, timeout=10):
    """Run a shell command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        logging.warning(f"Command timed out: {cmd}")
        return "", -1
    except Exception as e:
        logging.error(f"Command failed: {cmd}, error: {e}")
        return "", -1


def record_fence_event(action, target_node, gfs2_filesystems, status, details=""):
    """Record fencing event to structured log files"""
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    iso_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    recorder_node = socket.gethostname()
    
    # JSON Lines format for detailed logging
    log_entry = {
        "timestamp": iso_timestamp,
        "action": action,
        "target_node": target_node,
        "gfs2_filesystems": gfs2_filesystems,
        "status": status,
        "details": details,
        "recorder_node": recorder_node,
        "pacemaker_action": action
    }
    
    # Append to JSON Lines file
    fence_events_json = os.path.join(LOG_DIR, "fence-events-detailed.jsonl")
    try:
        with open(fence_events_json, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logging.error(f"Failed to write JSON log: {e}")
    
    # Human-readable log
    readable_log = os.path.join(LOG_DIR, "fence-events-readable.log")
    gfs2_str = json.dumps(gfs2_filesystems)
    readable_entry = f"[{timestamp}] ACTION={action} TARGET={target_node} GFS2={gfs2_str} STATUS={status} DETAILS={details}"
    try:
        with open(readable_log, 'a') as f:
            f.write(readable_entry + '\n')
    except Exception as e:
        logging.error(f"Failed to write readable log: {e}")
    
    logging.info(f"Recorded fence event: action={action}, target={target_node}, status={status}")


def write_fence_request(action, target_node, gfs2_filesystems):
    """
    Write a fence request file for external fencing component to process
    
    Returns the request_id (UUID) for tracking
    """
    request_id = str(uuid.uuid4())
    request_file = os.path.join(REQUEST_DIR, f"{request_id}.json")
    
    request_data = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target_node": target_node,
        "gfs2_filesystems": gfs2_filesystems,
        "recorder_node": socket.gethostname()
    }
    
    try:
        with open(request_file, 'w') as f:
            f.write(json.dumps(request_data, indent=2))
        logging.info(f"Wrote fence request: {request_file}")
        return request_id
    except Exception as e:
        logging.error(f"Failed to write fence request: {e}")
        return None


def wait_for_fence_response(request_id, timeout=60):
    """
    Wait for external fencing component to write response file
    
    Returns: (success: bool, message: str)
    """
    response_file = os.path.join(RESPONSE_DIR, f"{request_id}.json")
    start_time = time.time()
    poll_interval = 0.5  # Check every 500ms
    
    logging.info(f"Waiting for fence response: {response_file} (timeout={timeout}s)")
    
    while time.time() - start_time < timeout:
        if os.path.exists(response_file):
            try:
                with open(response_file, 'r') as f:
                    response_data = json.load(f)
                
                # Clean up response file
                try:
                    os.remove(response_file)
                except:
                    pass
                
                success = response_data.get("success", False)
                message = response_data.get("message", "Fence operation completed")
                actual_action = response_data.get("action_performed", "unknown")
                
                logging.info(f"Fence response received: success={success}, action={actual_action}, message={message}")
                
                return success, message, actual_action
                
            except Exception as e:
                logging.error(f"Failed to read fence response: {e}")
                return False, f"Failed to parse response: {e}", "error"
        
        time.sleep(poll_interval)
    
    # Timeout
    logging.error(f"Fence response timeout after {timeout}s")
    return False, f"Fence operation timed out after {timeout}s", "timeout"


def cleanup_old_requests(max_age_seconds=300):
    """Clean up request files older than max_age_seconds"""
    try:
        now = time.time()
        for filename in os.listdir(REQUEST_DIR):
            filepath = os.path.join(REQUEST_DIR, filename)
            if os.path.isfile(filepath):
                age = now - os.path.getmtime(filepath)
                if age > max_age_seconds:
                    os.remove(filepath)
                    logging.debug(f"Cleaned up old request: {filename}")
    except Exception as e:
        logging.warning(f"Failed to cleanup old requests: {e}")


def discover_gfs2_filesystems(compute_node):
    """Discover GFS2 filesystems accessible to a compute node"""
    
    # Check if discovery is enabled (re-read environment variable)
    discovery_enabled = os.environ.get("GFS2_DISCOVERY_ENABLED", "true").lower() == "true"
    if not discovery_enabled:
        logging.debug("GFS2 discovery disabled")
        return ["discovery-disabled"]
    
    logging.debug(f"Discovering GFS2 filesystems for compute node: {compute_node}")
    
    # Method 1: Try kubectl for NNF/Kubernetes-managed GFS2 (preferred)
    kubectl_result = try_kubectl_discovery(compute_node)
    if kubectl_result:
        logging.debug(f"kubectl discovery successful: {kubectl_result}")
        return kubectl_result
    
    # Method 2: Try DLM status via Pacemaker (reliable even when node is down)
    dlm_result = try_dlm_discovery(compute_node)
    if dlm_result:
        logging.debug(f"DLM discovery successful: {dlm_result}")
        return dlm_result
    
    # Method 3: Check Pacemaker resource status for GFS2 hints
    pacemaker_result = try_pacemaker_discovery(compute_node)
    if pacemaker_result:
        logging.debug(f"Pacemaker discovery successful: {pacemaker_result}")
        return pacemaker_result
    
    logging.debug(f"No GFS2 filesystems detected for {compute_node}")
    return ["none-detected"]


def try_kubectl_discovery(compute_node):
    """Try to discover GFS2 via kubectl and NNF resources"""
    # Check if kubectl is available
    kubectl_check = subprocess.run(["which", KUBECTL_CMD], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if kubectl_check.returncode != 0:
        logging.debug("kubectl not found, skipping Kubernetes discovery")
        return None
    
    # Try to get GFS2 filesystems via kubectl
    try:
        kubectl_cmd = f"{KUBECTL_CMD} get nnfstorage -A -o json 2>/dev/null"
        
        kubectl_result = subprocess.run(
            kubectl_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if kubectl_result.returncode == 0 and kubectl_result.stdout:
            try:
                data = json.loads(kubectl_result.stdout)
                gfs2_list = [
                    item['metadata']['name']
                    for item in data.get('items', [])
                    if item.get('spec', {}).get('fileSystemType') == 'gfs2'
                ]
                
                if gfs2_list:
                    logging.debug(f"Found GFS2 filesystems via kubectl: {gfs2_list}")
                    return gfs2_list
            except json.JSONDecodeError as e:
                logging.warning(f"Failed to parse kubectl JSON output: {e}")
        
    except subprocess.TimeoutExpired:
        logging.warning("kubectl command timed out")
    except Exception as e:
        logging.warning(f"kubectl GFS2 discovery failed: {e}")
    
    return None


def try_dlm_discovery(compute_node):
    """Try to discover GFS2 via DLM status in Pacemaker (works even when node is down)"""
    try:
        # Query Pacemaker for DLM and GFS2 resources related to this node
        pcs_cmd = f"pcs status resources 2>/dev/null | grep -E '(dlm|gfs2).*{compute_node}'"
        result = subprocess.run(
            pcs_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # Parse the output to extract GFS2 filesystem names
            lines = result.stdout.strip().split('\n')
            gfs2_filesystems = []
            
            for line in lines:
                # Look for patterns like "gfs2-storage-1" or "dlm:storage-name"
                if 'gfs2' in line.lower():
                    # Extract filesystem name from the resource line
                    parts = line.split()
                    for part in parts:
                        if 'gfs2' in part.lower() and ':' in part:
                            fs_name = part.split(':')[-1]
                            gfs2_filesystems.append(fs_name)
                        elif part.startswith('gfs2-'):
                            gfs2_filesystems.append(part.replace('gfs2-', ''))
            
            if gfs2_filesystems:
                logging.debug(f"Found GFS2 via DLM status: {gfs2_filesystems}")
                return list(set(gfs2_filesystems))  # Remove duplicates
        
    except Exception as e:
        logging.debug(f"DLM discovery failed: {e}")
    
    return None


def try_pacemaker_discovery(compute_node):
    """Try to discover GFS2 via Pacemaker cluster configuration"""
    try:
        # Check the cluster configuration for GFS2 resources
        pcs_cmd = "pcs config show 2>/dev/null | grep -E '(gfs2|dlm)' -A5 -B5"
        result = subprocess.run(
            pcs_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # Parse configuration for GFS2 resource definitions
            config_lines = result.stdout.strip().split('\n')
            gfs2_resources = []
            
            for line in config_lines:
                if 'gfs2' in line.lower() and ('resource' in line.lower() or 'primitive' in line.lower()):
                    # Extract resource name
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part.lower() in ['primitive', 'resource'] and i + 1 < len(parts):
                            resource_name = parts[i + 1]
                            if 'gfs2' in resource_name.lower():
                                gfs2_resources.append(resource_name.replace('gfs2-', ''))
            
            if gfs2_resources:
                logging.debug(f"Found GFS2 via Pacemaker config: {gfs2_resources}")
                return list(set(gfs2_resources))
        
    except Exception as e:
        logging.debug(f"Pacemaker config discovery failed: {e}")
    
    return None


def check_dlm_locks(compute_node):
    """Check if compute node has active DLM locks (indicates GFS2 usage)"""
    
    logging.debug(f"Checking DLM locks for: {compute_node}")
    
    try:
        pcs_cmd = f"pcs status resources 2>/dev/null | grep -i 'dlm.*{compute_node}' | wc -l"
        result = subprocess.run(
            pcs_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode == 0:
            dlm_count = int(result.stdout.strip() or "0")
            if dlm_count > 0:
                logging.debug(f"DLM active on {compute_node} (GFS2 likely in use)")
                return True
            else:
                logging.debug(f"No DLM activity detected on {compute_node}")
                return False
    except Exception as e:
        logging.warning(f"DLM check failed: {e}")
    
    return False


def do_action_monitor(options):
    """Monitor action - check if the fence recorder can operate"""
    
    target = options.get("--plug", options.get("--port", "unknown"))
    logging.debug(f"Monitor action for {target}")
    
    # Check if log directory is writable
    if not os.access(LOG_DIR, os.W_OK):
        logging.error(f"Log directory {LOG_DIR} is not writable")
        return 1
    
    # Check if we can discover GFS2 (if enabled)
    if GFS2_DISCOVERY_ENABLED:
        kubectl_check = subprocess.run(["which", KUBECTL_CMD], capture_output=True)
        if kubectl_check.returncode == 0:
            logging.debug("kubectl available for GFS2 discovery")
        else:
            logging.debug("kubectl not available, GFS2 discovery will be limited")
    
    logging.debug("Monitor successful - fence recorder operational")
    return 0


def do_fence_action(conn, options):
    """Execute fence action and record it"""
    
    action = options.get("--action", "unknown")
    target = options.get("--plug", options.get("--port", "unknown"))
    
    logging.info(f"Fence action requested: {action} for target: {target}")
    
    # Discover GFS2 filesystems
    gfs2_filesystems = discover_gfs2_filesystems(target)
    
    logging.info(f"GFS2 filesystems for {target}: {gfs2_filesystems}")
    
    # Record the fence event
    record_fence_event(
        action,
        target,
        gfs2_filesystems,
        "initiated",
        f"Fence action {action} initiated by Pacemaker"
    )
    
    # This is a RECORDER only - it doesn't actually perform fencing
    # The actual fencing is done by the external component watching the requests.
    # We just log the event
    
    logging.info("Fence event recorded successfully")
    
    # Return success - we successfully recorded the event
    return 0


def define_new_opts():
    """Define additional options specific to this fence agent"""
    
    all_opt["log_dir"] = {
        "getopt": ":",
        "longopt": "log-dir",
        "help": "--log-dir=[path]          Directory for fence event logs",
        "required": "0",
        "shortdesc": "Log directory",
        "default": "/var/log/gfs2-fencing",
        "order": 1
    }
    
    all_opt["no_gfs2_discovery"] = {
        "getopt": "",
        "longopt": "no-gfs2-discovery",
        "help": "--no-gfs2-discovery       Disable automatic GFS2 filesystem discovery",
        "required": "0",
        "shortdesc": "Disable GFS2 discovery",
        "default": "false",
        "order": 2
    }


def main():
    """Main entry point"""
    
    device_opt = ["no_password", "no_login", "port", "log_dir", "no_gfs2_discovery"]
    
    atexit.register(atexit_handler)
    
    define_new_opts()
    
    options = check_input(device_opt, process_input(device_opt))
    
    # Update global config from options
    global LOG_DIR, FENCE_LOG, GFS2_DISCOVERY_ENABLED
    
    if "--log-dir" in options:
        LOG_DIR = options["--log-dir"]
        FENCE_LOG = os.path.join(LOG_DIR, "fence-events.log")
        os.makedirs(LOG_DIR, exist_ok=True)
    
    if "--no-gfs2-discovery" in options:
        GFS2_DISCOVERY_ENABLED = False
    
    # Metadata and documentation
    docs = {}
    docs["shortdesc"] = "GFS2 fencing event recorder"
    docs["longdesc"] = """fence_gfs2_recorder is a specialized Pacemaker fence agent that runs on rabbit nodes to record GFS2-related fencing events.

This fence agent records GFS2 fencing events to structured log files. It attempts to discover which GFS2 filesystems are associated with the target compute node and logs comprehensive fencing information including:
- Timestamp
- Action (reboot/off/on)
- Target compute node
- GFS2 filesystems involved
- Fencing status

The agent integrates with Kubernetes/NNF infrastructure to discover GFS2 filesystem associations via NnfStorage resources.

Log Files Created:
- {LOG_DIR}/fence-events.log               - Main fence event log
- {LOG_DIR}/fence-events-readable.log      - Human-readable format
- {LOG_DIR}/fence-events-detailed.jsonl    - JSON Lines format for parsing
""".format(LOG_DIR=LOG_DIR)
    
    docs["vendorurl"] = "https://github.com/NearNodeFlash/fence-agents"
    
    show_docs(options, docs)
    
    run_delay(options)
    
    # Handle monitor action specially
    if options["--action"] == "monitor":
        sys.exit(do_action_monitor(options))
    
    # For all other actions, use request/response pattern
    target = options.get("--plug", "unknown")
    action = options["--action"]
    
    logging.info(f"Fence action requested: {action} for target: {target}")
    
    # Cleanup old requests before creating new one
    cleanup_old_requests()
    
    # Discover GFS2 filesystems
    gfs2_filesystems = discover_gfs2_filesystems(target)
    
    logging.info(f"GFS2 filesystems for {target}: {gfs2_filesystems}")
    
    # Record the fence event (initial log)
    record_fence_event(
        action,
        target,
        gfs2_filesystems,
        "requested",
        f"Fence action {action} requested by Pacemaker"
    )
    
    # Write fence request for external component
    request_id = write_fence_request(action, target, gfs2_filesystems)
    
    if not request_id:
        logging.error("Failed to write fence request")
        record_fence_event(action, target, gfs2_filesystems, "failed", "Failed to create fence request file")
        sys.exit(1)
    
    # Wait for external fencing component to respond
    success, message, actual_action = wait_for_fence_response(request_id, timeout=FENCE_TIMEOUT)
    
    # Record the final result
    if success:
        record_fence_event(
            action,
            target,
            gfs2_filesystems,
            "completed",
            f"Fence action {actual_action} completed successfully: {message}"
        )
        logging.info(f"Fence operation successful: {message}")
        sys.exit(0)
    else:
        record_fence_event(
            action,
            target,
            gfs2_filesystems,
            "failed",
            f"Fence action {action} failed: {message}"
        )
        logging.error(f"Fence operation failed: {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
