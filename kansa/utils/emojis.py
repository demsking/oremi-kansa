# Copyright 2025-2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import re

EMOJI_PATTERN = re.compile(
  "["
  "\U0001f600-\U0001f64f"  # emoticons
  "\U0001f300-\U0001f5ff"  # symbols & pictographs
  "\U0001f680-\U0001f6ff"  # transport & map symbols
  "\U0001f1e0-\U0001f1ff"  # flags
  "\U00002700-\U000027bf"  # dingbats
  "\U0001f900-\U0001f9ff"  # supplemental symbols and pictographs
  "\U00002600-\U000026ff"  # miscellaneous symbols
  "\U0001fa70-\U0001faff"  # symbols and pictographs extended-A
  "\U000025a0-\U000025ff"  # geometric shapes
  "]+",
  flags=re.UNICODE,
)


def remove_emojis(text: str) -> str:
  return EMOJI_PATTERN.sub("", text)
