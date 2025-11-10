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
External Fence Watcher - Simulates external component that performs actual fencing

This script watches the fence request directory and simulates performing
the fence action, then writes a response file for fence_recorder.

In production, replace this with your actual fencing mechanism.
"""

import os
import sys
import json
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

REQUEST_DIR = os.environ.get("REQUEST_DIR", "/localdisk/fence-recorder/requests")
RESPONSE_DIR = os.environ.get("RESPONSE_DIR", "/localdisk/fence-recorder/responses")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class FenceRequestHandler(FileSystemEventHandler):
    """Handle fence request files"""
    
    def __init__(self):
        self.processed_files = set()
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        if not event.src_path.endswith('.json'):
            return
        
        # Skip if already processed
        if event.src_path in self.processed_files:
            return
        
        # Wait for file to be fully written
        if self.wait_for_file_complete(event.src_path):
            self.processed_files.add(event.src_path)
            self.process_fence_request(event.src_path)
    
    def wait_for_file_complete(self, filepath, timeout=5):
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
    
    def process_fence_request(self, request_file):
        """Process a fence request and write response"""
        try:
            with open(request_file, 'r') as f:
                request_data = json.load(f)
            
            request_id = request_data.get("request_id")
            action = request_data.get("action")
            target_node = request_data.get("target_node")
            filesystems = request_data.get("filesystems", [])
            
            logging.info(f"Processing fence request: id={request_id}, action={action}, target={target_node}")
            
            # ============================================================
            # REPLACE THIS SECTION WITH YOUR ACTUAL FENCING MECHANISM
            # ============================================================
            
            # Simulate fence operation (in production, do actual fencing here)
            success = self.perform_fence_action(action, target_node)
            
            # ============================================================
            # END OF SECTION TO REPLACE
            # ============================================================
            
            # Write response with target node name prefix
            response_file = os.path.join(RESPONSE_DIR, f"{target_node}-{request_id}.json")
            response_data = {
                "request_id": request_id,
                "success": success,
                "action_performed": action,
                "target_node": target_node,
                "message": f"Fence {action} {'succeeded' if success else 'failed'} for {target_node}",
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
            
        except Exception as e:
            logging.error(f"Failed to process fence request {request_file}: {e}")
    
    def perform_fence_action(self, action, target_node):
        """
        Perform the actual fence action
        
        REPLACE THIS WITH YOUR ACTUAL FENCING MECHANISM
        
        Examples:
        - Call IPMI fence agent
        - Call cloud provider API
        - Call hardware management interface
        - Send command to PDU
        etc.
        """
        logging.info(f"[SIMULATED] Performing fence action: {action} on {target_node}")
        
        # Simulate fence operation time
        time.sleep(2)
        
        # In this simulation, always succeed
        # In production, return True only if fence actually succeeded
        return True


def main():
    """Main entry point"""
    
    # Ensure directories exist
    os.makedirs(REQUEST_DIR, exist_ok=True)
    os.makedirs(RESPONSE_DIR, exist_ok=True)
    
    logging.info(f"Starting fence request watcher...")
    logging.info(f"  Request directory: {REQUEST_DIR}")
    logging.info(f"  Response directory: {RESPONSE_DIR}")
    
    event_handler = FenceRequestHandler()
    observer = Observer()
    observer.schedule(event_handler, REQUEST_DIR, recursive=False)
    observer.start()
    
    logging.info("Fence watcher started. Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Stopping fence watcher...")
    
    observer.join()


if __name__ == "__main__":
    main()
