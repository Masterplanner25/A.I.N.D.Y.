import { useState } from "react";
import { safeMap } from "../../utils/safe";

// What's the structure? (ARTICLE_ANSWERS_SPEC §5, phase D2). The goal (owner, 2026-11-08) is to reveal that there IS a
// structure: the skeleton, the openings that repeat, the patterns named on a button, and the shape the draft's series
// shares beside it. Nothing here is judged, scored or rewritten. The old repetition panel lives here now (decision 11):
// a repeat that belongs to a pattern is shown inside it, the rest on their own.

const KIND = {
  contrast: "contrast",
  list: "list",
  naming_sequence: "naming sequence",
  refrain: "refrain",
  parallel: "parallel",
  question_answer: "question and answer",
  other: "pattern",
};

function Instances({ items }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, 3);
  return (
    <ul className="mt-1 space-y-0.5">
      {safeMap(shown, (text, i) => <li key={i} className="text-xs text-gray-400 italic">“{text}”</li>)}
      {items.length > 3 &&
        <li>
          <button type="button" className="text-xs text-cyan-500 hover:text-cyan-300" onClick={() => setOpen(!open)}>
            {open ? "show fewer" : `and ${items.length - 3} more`}
          </button>
        </li>
      }
    </ul>
  );
}

function SeriesShape({ series, onPick, busy }) {
  const shape = series?.shape;
  return (
    <div className="space-y-2" data-testid="structure-series">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-bold text-white text-sm">Its series</h3>
        {series?.options?.length > 0 &&
          <select
            aria-label="Series"
            className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
            value={series.name || ""}
            disabled={busy}
            onChange={(e) => onPick(e.target.value)}
          >
            <option value="">{series.name ? "None" : "None (pick one)"}</option>
            {safeMap(series.options, (name) => <option key={name} value={name}>{name}</option>)}
          </select>
        }
      </div>
      {!series?.name ?
        <p className="text-xs text-gray-500">
          {series?.options?.length ? "The title doesn't start with one of your series. Pick one to see its shape." : "No confirmed series yet."}
        </p> :
        !shape || shape.pieces < 2 ?
          <p className="text-xs text-gray-500">Fewer than two published pieces with stored text: no shared shape yet.</p> :
          <div className="space-y-2 text-xs text-gray-300">
            <p className="text-gray-400">
              {shape.pieces} published pieces · usually about {shape.median_words} words in {shape.median_sections} sections
            </p>
            {shape.headings?.length > 0 &&
              <div>
                <p className="text-gray-500">Headings they share</p>
                <ul className="mt-1 space-y-0.5">
                  {safeMap(shape.headings, (h) =>
                    <li key={h.heading}>
                      {h.heading} <span className="text-gray-500">in {h.pieces} of {shape.pieces}</span>
                      <span className={h.in_draft ? "text-[#00ffaa]" : "text-gray-500"}> · {h.in_draft ? "in this draft" : "not in this draft"}</span>
                    </li>
                  )}
                </ul>
              </div>
            }
            {shape.closing_heading &&
              <p>
                They close on <span className="text-white">{shape.closing_heading.heading}</span>
                <span className="text-gray-500"> ({shape.closing_heading.pieces} of {shape.pieces})</span>
                <span className={shape.closing_heading.in_draft ? "text-[#00ffaa]" : "text-gray-500"}>
                  {" "}· {shape.closing_heading.in_draft ? "so does this draft" : "this draft doesn't"}
                </span>
              </p>
            }
            {safeMap([["openings", "Openings they share"], ["closings", "Closing lines they share"]], ([key, label]) =>
              shape[key]?.length > 0 &&
                <div key={key}>
                  <p className="text-gray-500">{label}</p>
                  <ul className="mt-1 space-y-0.5">
                    {safeMap(shape[key], (o) =>
                      <li key={o.starts}>“{o.starts} …” <span className="text-gray-500">in {o.pieces} of {shape.pieces}</span></li>
                    )}
                  </ul>
                </div>
            )}
          </div>
      }
    </div>
  );
}

export default function StructurePanel({ structure, patterns, onPickSeries, busy }) {
  if (!structure && !patterns) return null;
  const sk = structure?.skeleton;
  const repeats = structure?.repeats;
  return (
    <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-xl shadow-lg md:col-span-2 space-y-5" data-testid="structure">
      <div>
        <h2 className="text-xl font-bold mb-1 text-purple-400 border-b border-zinc-800 pb-2">Structure</h2>
        <p className="text-xs text-gray-500 mt-2">How your draft is built and what it repeats. Nothing here is judged or rewritten for you.</p>
      </div>

      {patterns &&
        <div data-testid="structure-patterns">
          <h3 className="font-bold text-white text-sm">Patterns</h3>
          {patterns.patterns?.length ?
            <ul className="mt-2 space-y-3">
              {safeMap(patterns.patterns, (p, i) =>
                <li key={"p-" + i} className="text-sm">
                  <p className="text-white"><span className="text-xs text-purple-300 mr-2">{KIND[p.kind] || "pattern"}</span>{p.name}</p>
                  <Instances items={p.instances || []} />
                </li>
              )}
            </ul> :
            <p className="text-sm text-gray-400 mt-1">No patterns named: {patterns.reason || "nothing was returned"}.</p>
          }
        </div>
      }

      {structure &&
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-5">
            {sk &&
              <div>
                <h3 className="font-bold text-white text-sm">Skeleton</h3>
                <p className="text-xs text-gray-500">{sk.words} words · {sk.paragraphs} paragraphs · {sk.sections?.length || 0} sections</p>
                <ol className="mt-2 space-y-0.5">
                  {safeMap(sk.sections || [], (s, i) =>
                    <li key={"s-" + i} className="text-xs text-gray-300">
                      {s.heading || <span className="text-gray-500">(before the first heading)</span>}
                      <span className="text-gray-500"> · {s.words} words ({s.share}%)</span>
                    </li>
                  )}
                </ol>
                {sk.opening && <p className="mt-2 text-xs text-gray-400"><span className="text-gray-500">Opens: </span>“{sk.opening}”</p>}
                {sk.closing && <p className="mt-1 text-xs text-gray-400"><span className="text-gray-500">Closes: </span>“{sk.closing}”</p>}
              </div>
            }

            {structure.openings?.length > 0 &&
              <div>
                <h3 className="font-bold text-white text-sm">Sentences that start the same way</h3>
                <ul className="mt-2 space-y-3">
                  {safeMap(structure.openings, (o) =>
                    <li key={o.opening} className="text-sm text-gray-200">
                      “{o.opening} …” <span className="text-xs text-gray-500">{o.count} sentences</span>
                      {o.repeats?.length > 0 &&
                        <span className="text-xs text-gray-500"> · repeats inside: {safeMap(o.repeats, (r) => `“${r.phrase}” ${r.occurrences}×`).join(", ")}</span>
                      }
                      <Instances items={o.instances || []} />
                    </li>
                  )}
                </ul>
              </div>
            }

            {(repeats?.phrases?.length > 0 || repeats?.single_word_openers?.length > 0 || repeats?.overused_words?.length > 0) &&
              <div data-testid="structure-repeats">
                <h3 className="font-bold text-white text-sm">Other repeats</h3>
                <ul className="mt-2 space-y-1">
                  {safeMap((repeats.phrases || []).slice(0, 8), (phrase) =>
                    <li key={phrase.phrase} className="text-sm text-gray-300">
                      “{phrase.phrase}”
                      <span className="text-gray-500 text-xs"> — {phrase.occurrences}×{phrase.clustered ? ", close together" : ""}</span>
                    </li>
                  )}
                  {safeMap((repeats.single_word_openers || []).slice(0, 5), (opener) =>
                    <li key={"o-" + opener.opener} className="text-sm text-gray-300">
                      Sentences starting “{opener.opener}”
                      <span className="text-gray-500 text-xs"> — {opener.count} sentences ({opener.share}%)</span>
                    </li>
                  )}
                  {repeats.overused_words?.length > 0 &&
                    <li className="text-sm text-gray-300">
                      Words standing out: {safeMap(repeats.overused_words.slice(0, 8), (w) => `${w.word} ${w.occurrences}×`).join(", ")}
                    </li>
                  }
                </ul>
              </div>
            }
          </div>
          <SeriesShape series={structure.series} onPick={onPickSeries} busy={busy} />
        </div>
      }
    </div>
  );
}
