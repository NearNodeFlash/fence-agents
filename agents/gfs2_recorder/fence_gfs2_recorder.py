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

# Import configuration
try:
    from config import REQUEST_DIR, RESPONSE_DIR
except ImportError:
    # Fallback to default values if config.py not available
    REQUEST_DIR = "/localdisk/gfs2-fencing/requests"
    RESPONSE_DIR = "/localdisk/gfs2-fencing/responses"

# Configuration
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/gfs2-fencing")
FENCE_LOG = os.environ.get("FENCE_LOG", os.path.join(LOG_DIR, "fence-events.log"))
# REQUEST_DIR and RESPONSE_DIR now imported from config.py
FENCE_TIMEOUT = int(os.environ.get("FENCE_TIMEOUT", "60"))  # Default 60 second timeout

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


def record_fence_event(action, target_node, status, details=""):
    """Record fencing event to structured log files"""
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    iso_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    recorder_node = socket.gethostname()
    
    # JSON Lines format for detailed logging
    log_entry = {
        "timestamp": iso_timestamp,
        "action": action,
        "target_node": target_node,
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
    readable_entry = f"[{timestamp}] ACTION={action} TARGET={target_node} STATUS={status} DETAILS={details}"
    try:
        with open(readable_log, 'a') as f:
            f.write(readable_entry + '\n')
    except Exception as e:
        logging.error(f"Failed to write readable log: {e}")
    
    logging.info(f"Recorded fence event: action={action}, target={target_node}, status={status}")


def write_fence_request(action, target_node):
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
                
                # Do NOT delete response file - NNF software needs it to track fenced nodes
                
                success = response_data.get("success", False)
                message = response_data.get("message", "Fence operation completed")
                actual_action = response_data.get("action_performed", "unknown")
                
                logging.info(f"Fence response received: success={success}, action={actual_action}, message={message}")
                logging.info(f"Response file preserved at: {response_file}")
                
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





def do_action_monitor(options):
    """Monitor action - check if the fence recorder can operate"""
    
    target = options.get("--plug", options.get("--port", "unknown"))
    logging.debug(f"Monitor action for {target}")
    
    # Check if log directory is writable
    if not os.access(LOG_DIR, os.W_OK):
        logging.error(f"Log directory {LOG_DIR} is not writable")
        return 1
    
    logging.debug("Monitor successful - fence recorder operational")
    return 0


def do_fence_action(conn, options):
    """Execute fence action and record it"""
    
    action = options.get("--action", "unknown")
    target = options.get("--plug", options.get("--port", "unknown"))
    
    logging.info(f"Fence action requested: {action} for target: {target}")
    
    # Record the fence event
    record_fence_event(
        action,
        target,
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


def main():
    """Main entry point"""
    
    device_opt = ["no_password", "no_login", "port", "log_dir"]
    
    atexit.register(atexit_handler)
    
    define_new_opts()
    
    options = check_input(device_opt, process_input(device_opt))
    
    # Update global config from options
    global LOG_DIR, FENCE_LOG
    
    if "--log-dir" in options:
        LOG_DIR = options["--log-dir"]
        FENCE_LOG = os.path.join(LOG_DIR, "fence-events.log")
        os.makedirs(LOG_DIR, exist_ok=True)
    
    # Metadata and documentation
    docs = {}
    docs["shortdesc"] = "GFS2 fencing event recorder"
    docs["longdesc"] = """fence_gfs2_recorder is a specialized Pacemaker fence agent that runs on rabbit nodes to record fencing events via a request/response pattern.

This fence agent records fencing events to structured log files and writes fence requests for external components to process. It logs comprehensive fencing information including:
- Timestamp
- Action (reboot/off/on)
- Target compute node
- Fencing status

The agent writes fence requests to {REQUEST_DIR} and waits for responses in {RESPONSE_DIR}.

Log Files Created:
- {LOG_DIR}/fence-events.log               - Main fence event log
- {LOG_DIR}/fence-events-readable.log      - Human-readable format
- {LOG_DIR}/fence-events-detailed.jsonl    - JSON Lines format for parsing
""".format(LOG_DIR=LOG_DIR, REQUEST_DIR=REQUEST_DIR, RESPONSE_DIR=RESPONSE_DIR)
    
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
    
    # Record the fence event (initial log)
    record_fence_event(
        action,
        target,
        "requested",
        f"Fence action {action} requested by Pacemaker"
    )
    
    # Write fence request for external component
    request_id = write_fence_request(action, target)
    
    if not request_id:
        logging.error("Failed to write fence request")
        record_fence_event(action, target, "failed", "Failed to create fence request file")
        sys.exit(1)
    
    # Wait for external fencing component to respond
    success, message, actual_action = wait_for_fence_response(request_id, timeout=FENCE_TIMEOUT)
    
    # Record the final result and respond to Pacemaker via exit code
    # Pacemaker invokes this agent as a subprocess and checks the exit code:
    #   - Exit code 0 = fencing succeeded
    #   - Exit code 1 (or any non-zero) = fencing failed
    # This is the standard STONITH/fence agent protocol
    
    if success:
        record_fence_event(
            action,
            target,
            "completed",
            f"Fence action {actual_action} completed successfully: {message}"
        )
        logging.info(f"Fence operation successful: {message}")
        # Exit 0 tells Pacemaker: fencing succeeded
        sys.exit(0)
    else:
        record_fence_event(
            action,
            target,
            "failed",
            f"Fence action {action} failed: {message}"
        )
        logging.error(f"Fence operation failed: {message}")
        # Exit 1 tells Pacemaker: fencing failed
        sys.exit(1)


if __name__ == "__main__":
    main()
