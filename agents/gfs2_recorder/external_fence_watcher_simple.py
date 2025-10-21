#!/usr/bin/env python3

"""
External Fence Watcher (Simple Polling Version)

This script watches the fence request directory and simulates performing
the fence action, then writes a response file for fence_gfs2_recorder.

This version uses simple polling instead of inotify/watchdog.
In production, replace the perform_fence_action() function with your actual fencing mechanism.
"""

import os
import sys
import json
import time
import logging
import glob

REQUEST_DIR = os.environ.get("REQUEST_DIR", "/localdisk/gfs2-fencing/requests")
RESPONSE_DIR = os.environ.get("RESPONSE_DIR", "/localdisk/gfs2-fencing/responses")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "0.5"))  # Check every 500ms

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def perform_fence_action(action, target_node, gfs2_filesystems):
    """
    Perform the actual fence action
    
    REPLACE THIS WITH YOUR ACTUAL FENCING MECHANISM
    
    Examples:
    - Call fence_nnf or other fence agent
    - Call cloud provider API (AWS, Azure, GCP)
    - Call hardware management interface (IPMI, iLO, DRAC)
    - Send command to PDU
    - Call custom fencing script
    
    Args:
        action: "on", "off", "reboot", "status"
        target_node: hostname of node to fence
        gfs2_filesystems: list of GFS2 filesystems on this node
    
    Returns:
        tuple: (success: bool, message: str)
    """
    logging.info(f"[SIMULATED] Performing fence action: {action} on {target_node}")
    logging.info(f"[SIMULATED] GFS2 filesystems affected: {gfs2_filesystems}")
    
    # ============================================================
    # REPLACE THIS SECTION WITH YOUR ACTUAL FENCING MECHANISM
    # ============================================================
    
    # Example: Call fence_nnf
    # import subprocess
    # try:
    #     result = subprocess.run(
    #         ["/usr/sbin/fence_nnf", "--action", action, "--plug", target_node],
    #         capture_output=True,
    #         text=True,
    #         timeout=30
    #     )
    #     success = result.returncode == 0
    #     message = f"fence_nnf returned: {result.returncode}"
    #     return success, message
    # except Exception as e:
    #     return False, f"Fence operation failed: {e}"
    
    # For now, simulate fence operation
    time.sleep(2)  # Simulate fence delay
    
    return True, f"Simulated fence {action} succeeded for {target_node}"
    
    # ============================================================
    # END OF SECTION TO REPLACE
    # ============================================================


def process_fence_request(request_file):
    """Process a fence request and write response"""
    try:
        with open(request_file, 'r') as f:
            request_data = json.load(f)
        
        request_id = request_data.get("request_id")
        action = request_data.get("action")
        target_node = request_data.get("target_node")
        gfs2_filesystems = request_data.get("gfs2_filesystems", [])
        
        logging.info(f"Processing fence request: id={request_id}, action={action}, target={target_node}")
        
        # Perform the actual fence action
        success, message = perform_fence_action(action, target_node, gfs2_filesystems)
        
        # Write response
        response_file = os.path.join(RESPONSE_DIR, f"{request_id}.json")
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
