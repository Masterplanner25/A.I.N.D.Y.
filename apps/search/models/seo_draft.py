"""A draft, and its analyses over time — the unit that makes the SEO tool a loop.

`SEO_EDITING_AID_SPEC` §4. Every analysis the tool produced was a measurement taken once:
you could learn that a phrase repeats and a target is thin, act on both, re-run, and the tool
had no memory that the first reading ever happened. `search_history` rows exist but nothing
says two of them are the same piece at different times, so the before/after question — which
is most of why saving is wanted — could not be asked.

> *"The unit worth keeping is a draft and its analyses over time… without the draft as the
> unit, saving produces a pile of unrelated scorecards."*

★ **Every analysis is kept, and nothing is deleted without being asked.** Owner's call,
2026-09-07: *"every analysis with a prune/deletion every so often prompted by the system."*
That is the same shape settled twice already in this repo — the system proposes, the person
confirms (masterplan phase advance, worth declaration in Genesis) — and it is the right one
here for a specific reason: a silent cap would discard exactly the early analyses that make a
before/after comparison possible, and it would do it at the moment the history finally became
long enough to be interesting.

The unbounded-growth risk is real and this repo has been bitten by it once
(`HEALTH-EVENT-VOLUME-1`, 3.6 GB of health events). The answer here is a prompt, not a cap.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base


class SeoDraft(Base):
    """A piece of writing, before it is published.

    Publication is the boundary this side of which the writer can still change the work
    (`SEO_EDITING_AID_SPEC` §4). After it, the same piece becomes a RippleTrace drop point
    and can only be measured — which is why `published_url` is here: it is the one field that
    makes the two records matchable later, and the cheapest thing to carry now.
    """

    __tablename__ = "seo_drafts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Named by the writer, not by a timestamp. A list of "Analysis 2026-09-07 14:32" is a pile
    # of scorecards with dates on them, which is the thing this model exists to replace.
    name = Column(String(200), nullable=False)

    # The draft itself. Kept so a draft can be reopened, edited and re-analysed — without it
    # the history is a record of readings on text that no longer exists anywhere.
    content = Column(Text, nullable=False, default="")
    title = Column(String(500), nullable=True)

    # ★ Remembered per draft, which answers §5 open question 1. Retyping the targets on every
    # analysis is how they end up subtly different between runs, and two analyses measured
    # against different targets cannot be compared — silently, because nothing would say so.
    target_keywords = Column(JSON, nullable=True)

    # Set once the piece is published. The only path in this repo from "the tool said your
    # density was thin" to "and here is whether that mattered" runs through matching this to a
    # RippleTrace drop point.
    published_url = Column(String, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SeoDraft(id={self.id}, name={self.name!r})>"


class SeoDraftAnalysis(Base):
    """One reading of one draft, at one moment.

    The full result is kept as JSON because the analysis shape grows (title analysis, coverage
    and repetition all arrived after the first version) and a historical row must stay readable
    on its own terms rather than being reinterpreted by whatever the current shape is.

    The four scalar columns beside it are denormalised on purpose: comparing two analyses is
    the entire point of this table, and doing it by unpacking JSON on every read makes the
    common operation the expensive one.
    """

    __tablename__ = "seo_draft_analyses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    draft_id = Column(String, ForeignKey("seo_drafts.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    result = Column(JSON, nullable=False)

    word_count = Column(Integer, nullable=True)
    readability = Column(Float, nullable=True)
    search_score = Column(Float, nullable=True)
    # Kept alongside the result so a prune proposal can say what an old analysis measured
    # without deserialising every row it is offering to delete.
    title_characters = Column(Integer, nullable=True)

    # ★ The first analysis of a draft, protected from pruning. Not a user-set flag: it is
    # whatever came first, because "before" is only meaningful against the earliest reading —
    # and a prune that removes the baseline destroys the comparison it was making room for.
    is_baseline = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self):
        return f"<SeoDraftAnalysis(draft={self.draft_id}, at={self.created_at})>"
