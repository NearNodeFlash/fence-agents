#!/usr/bin/env python3

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


"""
External Fence Watcher (Simple Polling Version)

This script watches the fence request directory and simulates performing
the fence action, then writes a response file for fence_recorder.

This version uses simple polling instead of inotify/watchdog.
In production, replace the perform_fence_action() function with your actual fencing mechanism.
"""

import os
import sys
import json
import time
import logging
import glob

REQUEST_DIR = os.environ.get("REQUEST_DIR", "/localdisk/fence-recorder/requests")
RESPONSE_DIR = os.environ.get("RESPONSE_DIR", "/localdisk/fence-recorder/responses")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "0.5"))  # Check every 500ms

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def perform_fence_action(action, target_node, filesystems):
    """
    Perform the actual fence action
    
    REPLACE THIS WITH YOUR ACTUAL FENCING MECHANISM
    
    Examples:
    - Call fence_ipmi or other fence agent
    - Call cloud provider API (AWS, Azure, GCP)
    - Call hardware management interface (IPMI, iLO, DRAC)
    - Send command to PDU
    - Call custom fencing script
    
    Args:
        action: "on", "off", "reboot", "status"
        target_node: hostname of node to fence
        filesystems: list of shared filesystems on this node
    
    Returns:
        tuple: (success: bool, message: str)
    """
    logging.info(f"[SIMULATED] Performing fence action: {action} on {target_node}")
    logging.info(f"[SIMULATED] shared filesystems affected: {filesystems}")
    
    # ============================================================
    # REPLACE THIS SECTION WITH YOUR ACTUAL FENCING MECHANISM
    # ============================================================
    
    # Example: Call fence_ipmi
    # import subprocess
    # try:
    #     result = subprocess.run(
    #         ["/usr/sbin/fence_ipmi", "--action", action, "--ip", target_node],
    #         capture_output=True,
    #         text=True,
    #         timeout=30
    #     )
    #     success = result.returncode == 0
    #     message = f"fence_ipmi returned: {result.returncode}"
    #     return success, message
    # except Exception as e:
    #     return False, f"Fence operation failed: {e}"
    
    # For now, simulate fence operation
    time.sleep(2)  # Simulate fence delay
    
    return True, f"Simulated fence {action} succeeded for {target_node}"
    
    # ============================================================
    # END OF SECTION TO REPLACE
    # ============================================================


def wait_for_file_complete(filepath, timeout=5):
    """Wait for file to be completely written"""
    start_time = time.time()
    last_size = -1
    
    while time.time() - start_time < timeout:
        try:
            current_size = os.path.getsize(filepath)
            if current_size == last_size and current_size > 0:
                # Size hasn't changed, file is likely complete
                time.sleep(0.1)  # One more small delay to be sure
                return True
            last_size = current_size
            time.sleep(0.1)
        except (OSError, FileNotFoundError):
            # File might be in the process of being written
            time.sleep(0.1)
            continue
    
    logging.warning(f"Timeout waiting for {filepath} to be fully written")
    return False


def process_fence_request(request_file):
    """Process a fence request and write response"""
    try:
        # Wait for file to be fully written before reading
        if not wait_for_file_complete(request_file):
            logging.error(f"File {request_file} was not fully written in time")
            return False
        
        with open(request_file, 'r') as f:
            request_data = json.load(f)
        
        request_id = request_data.get("request_id")
        action = request_data.get("action")
        target_node = request_data.get("target_node")
        filesystems = request_data.get("filesystems", [])
        
        logging.info(f"Processing fence request: id={request_id}, action={action}, target={target_node}")
        
        # Perform the actual fence action
        success, message = perform_fence_action(action, target_node, filesystems)
        
        # Write response with target node name prefix
        response_file = os.path.join(RESPONSE_DIR, f"{target_node}-{request_id}.json")
        response_data = {
            "request_id": request_id,
            "success": success,
            "action_performed": action,
            "target_node": target_node,
            "message": message,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        
        with open(response_file, 'w') as f:
            f.write(json.dumps(response_data, indent=2))
        
        logging.info(f"Wrote fence response: success={success}, file={response_file}")
        
        # Clean up request file
        try:
            os.remove(request_file)
        except:
            pass
        
        return True
        
    except Exception as e:
        logging.error(f"Failed to process fence request {request_file}: {e}")
        return False


def main():
    """Main entry point"""
    
    # Ensure directories exist
    os.makedirs(REQUEST_DIR, exist_ok=True)
    os.makedirs(RESPONSE_DIR, exist_ok=True)
    
    logging.info(f"Starting fence request watcher (polling mode)...")
    logging.info(f"  Request directory: {REQUEST_DIR}")
    logging.info(f"  Response directory: {RESPONSE_DIR}")
    logging.info(f"  Poll interval: {POLL_INTERVAL}s")
    
    processed_files = set()
    
    logging.info("Fence watcher started. Press Ctrl+C to stop.")
    
    try:
        while True:
            # Find all JSON files in request directory
            request_files = glob.glob(os.path.join(REQUEST_DIR, "*.json"))
            
            for request_file in request_files:
                # Skip if already processed
                if request_file in processed_files:
                    continue
                
                # Process the request
                if process_fence_request(request_file):
                    processed_files.add(request_file)
                
                # Cleanup processed set if it gets too large
                if len(processed_files) > 1000:
                    processed_files.clear()
            
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        logging.info("Stopping fence watcher...")
        sys.exit(0)


if __name__ == "__main__":
    main()
