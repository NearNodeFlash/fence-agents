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
Fence Recorder Configuration

These paths are used by the fence recorder agent and external response systems.
If you change these values, ensure all integrated systems are updated.
"""

# Directory where fence agents write fence request files
REQUEST_DIR = "/localdisk/fence-recorder/requests"

# Directory where external systems write fence response files
RESPONSE_DIR = "/localdisk/fence-recorder/responses"
