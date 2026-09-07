from pydantic import BaseModel
from typing import Optional


class SEOInput(BaseModel):
    text: str
    top_n: Optional[int] = 10
    # Optional, and new. The tool had no concept of a title — it took one blob of body text
    # — so it could report on a draft without ever looking at the line a search result shows
    # (TITLE_AS_CONTAINER_SPEC §6). Omitted, every response is unchanged.
    title: Optional[str] = None


class MetaInput(BaseModel):
    text: str
    limit: Optional[int] = 160

class TitleInput(BaseModel):
    text: str
    count: Optional[int] = 5
    # The writer's own title, when they have one. Input only — `generate_title_candidates`
    # echoes it back untouched and never returns a replacement for it.
    current_title: Optional[str] = None
    target_keywords: Optional[list[str]] = None
