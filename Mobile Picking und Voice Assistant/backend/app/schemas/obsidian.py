from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ObsidianLogRequest(BaseModel):
    message: str
    category: Optional[str] = "QA-ALARM"
    timestamp: Optional[datetime] = None
