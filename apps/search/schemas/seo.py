from pydantic import BaseModel
from typing import Optional


class SEOInput(BaseModel):
    text: str
    top_n: Optional[int] = 10
    # Optional, and new. The tool had no concept of a title — it took one blob of body text
    # — so it could report on a draft without ever looking at the line a search result shows
    # (TITLE_AS_CONTAINER_SPEC §6). Omitted, every response is unchanged.
    title: Optional[str] = None
    # The terms the writer is aiming at. Supplied, the tool answers "am I covering what I am
    # trying to rank for" instead of "what words appear most often" (SEO_EDITING_AID_SPEC §2).
    target_keywords: Optional[list[str]] = None


class MetaInput(BaseModel):
    text: str
    limit: Optional[int] = 160
    # The writer's title: its framing is what the description keeps (`meta_generation`).
    title: Optional[str] = None

class ArticleAnswersInput(BaseModel):
    """What questions an article answers (ARTICLE_ANSWERS_SPEC §2). The writer's title is context."""
    text: str
    title: Optional[str] = None


class ArticleClaimsInput(BaseModel):
    """What a draft claims, and what each claim leans on (ARTICLE_ANSWERS_SPEC §4, phase D1)."""
    text: str
    title: Optional[str] = None


class StructureInput(BaseModel):
    """The draft's structure beside its series (ARTICLE_ANSWERS_SPEC §5, phase D2). ``series`` names one of the
    writer's confirmed series; without it the series is taken from the title's prefix, when it has one."""
    text: str
    title: Optional[str] = None
    series: Optional[str] = None


class OwnLinksInput(BaseModel):
    """The owner's pieces a draft links to and could link to (ARTICLE_ANSWERS_SPEC §3).

    ``title`` and ``exclude_url`` name the draft itself when it is already published, so it is
    never offered as a link to itself."""
    text: str
    title: Optional[str] = None
    exclude_url: Optional[str] = None
    limit: Optional[int] = 8


class TitleInput(BaseModel):
    text: str
    count: Optional[int] = 5
    # The writer's own title, when they have one. Input only — `generate_title_candidates`
    # echoes it back untouched and never returns a replacement for it.
    current_title: Optional[str] = None
    target_keywords: Optional[list[str]] = None


class DraftCreateInput(BaseModel):
    name: str
    content: Optional[str] = ""
    title: Optional[str] = None
    target_keywords: Optional[list[str]] = None


class DraftUpdateInput(BaseModel):
    # Every field optional and `None` means "not supplied": omitting a key must never wipe it,
    # while an explicit empty string still clears one.
    name: Optional[str] = None
    content: Optional[str] = None
    title: Optional[str] = None
    target_keywords: Optional[list[str]] = None
    published_url: Optional[str] = None


class DraftAnalyzeInput(BaseModel):
    """Analyse a draft and attach the reading to it.

    Nothing is sent: the draft already holds its content, title and target keywords, which is
    the point of it being a unit. `top_n` is the only knob.
    """

    top_n: Optional[int] = 10


class DraftPruneInput(BaseModel):
    """Ids the person confirmed, not a request to recompute what is prunable.

    Between a proposal and its answer a new analysis may have been recorded; a prune that
    re-derived the set would delete something the person was never shown.
    """

    analysis_ids: list[str]
