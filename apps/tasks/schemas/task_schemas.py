# /models/task_schemas.py
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class TaskDependency(BaseModel):
    task_id: int
    dependency_type: str = "hard"


class TaskCreate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None  # accepted as alias for name
    category: Optional[str] = "general"
    priority: Optional[str] = "medium"
    estimated_hours: Optional[float] = None  # estimated effort in hours -> Task.duration
    due_date: Optional[str] = None
    masterplan_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    dependency_type: Optional[str] = "hard"
    dependencies: List[TaskDependency] = Field(default_factory=list)
    automation_type: Optional[str] = None
    automation_config: Optional[dict] = None
    scheduled_time: Optional[str] = None
    reminder_time: Optional[str] = None
    recurrence: Optional[str] = None  # "daily", "weekly", "monthly"

    @model_validator(mode="before")
    @classmethod
    def resolve_name_from_title(cls, values):
        if not values.get("name") and values.get("title"):
            values["name"] = values["title"]
        return values

    @model_validator(mode="after")
    def validate_name_present(self):
        if not self.name:
            raise ValueError("name is required")
        return self

class TaskAction(BaseModel):
    name: str
    # Optional 1-5 judgements, supplied on completion only. They feed WCU
    # (`effort x complexity x difficulty`) and were permanently 1 until this was collected.
    # Optional rather than required so `/start` and `/pause`, which share this schema, are
    # unaffected, and so a caller that cannot judge omits them instead of inventing a value.
    task_complexity: int | None = None
    task_difficulty: int | None = None
