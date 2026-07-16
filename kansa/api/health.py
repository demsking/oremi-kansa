# Copyright 2026 Sébastien Demanou. All Rights Reserved.
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
from typing import Literal

from fastapi import APIRouter
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field

from ..core.package import APP_VERSION


API_TAG_METADATA = {
  "name": "Server Endpoints",
  "description": (
    "Operational health and readiness endpoints. Use this tag for lightweight "
    "checks that confirm the API process is alive and report basic runtime "
    "metadata such as the version."
  ),
}

router = APIRouter(prefix="/health", tags=[API_TAG_METADATA["name"]])


class ServerStatus(BaseModel):
  status: Literal["ok", "degraded"] = Field()
  version: str = Field(..., description="Version of the application.")


@router.get(
  "/",
  summary="Health check",
  description=(
    "Return a lightweight health response for load balancers, Docker health "
    "checks, and monitoring tools. The response confirms the API is alive and "
    "includes the application version."
  ),
  responses={
    200: {
      "content": {
        "application/json": {
          "example": ServerStatus.model_validate(
            {
              "status": "ok",
              "version": APP_VERSION,
            }
          )
        }
      }
    }
  },
)
async def health(request: Request) -> ServerStatus:
  return ServerStatus(
    status="ok",
    version=APP_VERSION,
  )
