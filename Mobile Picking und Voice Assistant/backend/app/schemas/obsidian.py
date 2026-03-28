from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

class ObsidianLogRequest(BaseModel):
    message: str
    category: Optional[str] = "QA-ALARM"
    timestamp: Optional[datetime] = None


class ObsidianSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    limit: int = Field(default=3, ge=1, le=10)
