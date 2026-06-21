from pydantic import BaseModel
from typing import Optional

class DepartmentFilter(BaseModel):
    jobTitle:  Optional[str] = ""
    empStatus: Optional[str] = ""
    subUnit:   Optional[str] = ""

class ScrapeRequest(BaseModel):
    job_id:        Optional[str] = ""
    max_employees: Optional[int] = 10
    department:    Optional[DepartmentFilter] = None