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
