import { useState } from "react";
import {
  analyzeSeo as apiAnalyzeSeo,
  generateMeta as apiGenerateMeta,
  generateTitles as apiGenerateTitles,
  suggestSeoImprovements as apiSuggestSeoImprovements,
} from "../../api/search.js";
import { safeMap } from "../../utils/safe";
import SearchHistory from "./SearchHistory";

// SERP budgets, in CHARACTERS. Mirrored from `seo_services.py` so the counter can respond as
// the writer types rather than after a round trip; the server stays authoritative and returns
// its own `budget` with every analysis.
const TITLE_CHAR_BUDGET = 60;

// A word count that matches the server's: `re.findall(r"\b\w+\b")`. Shown live because the
// count only appeared after Analyze was clicked, and a count you have to ask for is not much
// use while you are still writing (TITLE_AS_CONTAINER_SPEC §6a).
function countWords(text) {
  const matches = (text || "").match(/[\p{L}\p{N}_]+/gu);
  return matches ? matches.length : 0;
}

export default function AiSeoTool() {
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [seoData, setSeoData] = useState(null);
  const [metaDescription, setMetaDescription] = useState("");
  const [metaCharacters, setMetaCharacters] = useState(null);
  const [titleOptions, setTitleOptions] = useState(null);
  const [seoSuggestions, setSeoSuggestions] = useState("");
  const [loading, setLoading] = useState(false);
  // Bumped after a successful analyze so the "Recent SEO Analyses" panel refetches — the
  // analysis is saved server-side, but the panel only loaded once on mount, so a freshly-run
  // analysis never appeared until a page reload ("No saved searches yet").
  const [historyRefresh, setHistoryRefresh] = useState(0);

  const handleHistorySelect = (item) => {
    const stored = item.result || {};
    setContent(stored.query || item.query || "");
    setTitle(stored.title_analysis?.title || "");
    setSeoData(stored);
    setMetaDescription("");
    setMetaCharacters(null);
    setTitleOptions(null);
    setSeoSuggestions("");
  };

  const analyzeSeo = async () => {
    setLoading(true);
    try {
      const data = await apiAnalyzeSeo(content, title);
      setSeoData(data);
      setHistoryRefresh((n) => n + 1); // the analysis was just saved — refresh the recent list
    } catch (error) {
      console.error("SEO Analysis Error: ", error);
    }
    setLoading(false);
  };

  const generateMeta = async () => {
    setLoading(true);
    try {
      const data = await apiGenerateMeta(content);
      setMetaDescription(data.meta_description);
      setMetaCharacters(data.characters ?? null);
    } catch (error) {
      console.error("Meta Description Error: ", error);
    }
    setLoading(false);
  };

  const generateTitles = async () => {
    setLoading(true);
    try {
      const data = await apiGenerateTitles(content, title);
      setTitleOptions(data);
    } catch (error) {
      console.error("Title Generation Error: ", error);
      // Never a fabricated fallback: a locally-assembled title would look exactly like a
      // suggestion, and the writer could not tell a proposal from a failure.
      setTitleOptions({ candidates: [], reason: "the title service could not be reached" });
    }
    setLoading(false);
  };

  const getSeoSuggestions = async () => {
    setLoading(true);
    try {
      const data = await apiSuggestSeoImprovements(content);
      setSeoSuggestions(data.seo_suggestions);
    } catch (error) {
      console.error("SEO Suggestions Error: ", error);
    }
    setLoading(false);
  };

  return (
    <div className="container mx-auto p-6 text-white bg-black min-h-screen">
            <h1 className="text-3xl font-bold mb-2 text-blue-400">AI SEO Optimization Tool</h1>
            {/* Neither this tool nor RippleTrace said which phase of the work it was for, so
                a draft and a published article looked like the same kind of thing. They are
                two stages of one lifecycle split by publication: before it you can still
                change the piece, after it you can only measure it. Stating it here is
                cheapest BEFORE drafts are saved, because saving is what makes the two
                surfaces start to look alike (both listing your articles). */}
            <p className="text-sm text-gray-400 mb-6">
                <span className="text-gray-300">Before you publish.</span>{" "}
                Analyse and refine a draft here. Once it is published, track what happened to
                it in{" "}
                <a href="/rippletrace" className="text-blue-400 hover:text-blue-300 underline">
                    RippleTrace
                </a>.
            </p>
            
            {/* TITLE — optional. The tool had no concept of a title at all, so it could
                report on a draft without ever looking at the line a search result shows. */}
            <div className="mb-4">
                <div className="flex items-baseline justify-between mb-2">
                    <label htmlFor="seo-title" className="block text-sm font-medium text-gray-400">
                        Title <span className="text-gray-600">(optional)</span>
                    </label>
                    {title &&
                      <span
                        className={`text-xs ${title.length > TITLE_CHAR_BUDGET ? "text-amber-400" : "text-gray-500"}`}
                        data-testid="title-character-count">
                        {title.length} / {TITLE_CHAR_BUDGET} characters
                      </span>
                    }
                </div>
                <input
          id="seo-title"
          type="text"
          className="w-full p-3 bg-zinc-900 border border-zinc-700 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-hidden transition-all"
          placeholder="The headline a search result will show..."
          value={title}
          onChange={(e) => setTitle(e.target.value)} />
            </div>

            {/* TEXTAREA SECTION */}
            <div className="mb-4">
                <div className="flex items-baseline justify-between mb-2">
                    <label className="block text-sm font-medium text-gray-400">Article Content</label>
                    {content &&
                      <span className="text-xs text-gray-500" data-testid="live-word-count">
                        {countWords(content)} words
                      </span>
                    }
                </div>
                <textarea
          className="w-full p-4 bg-zinc-900 border border-zinc-700 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-hidden transition-all"
          rows="8"
          placeholder="Paste your article or blog content here for analysis..."
          value={content}
          onChange={(e) => setContent(e.target.value)}>
        </textarea>
            </div>

            {/* ACTION BUTTONS */}
            <div className="flex flex-wrap gap-4 mt-4">
                <button
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-md transition-colors disabled:opacity-50"
          onClick={analyzeSeo}
          disabled={loading || !content}>
          
                    Analyze SEO
                </button>
                <button
          className="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-md transition-colors disabled:opacity-50"
          onClick={generateMeta}
          disabled={loading || !content}>
          
                    Generate Meta Description
                </button>
                <button
          className="px-6 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-md transition-colors disabled:opacity-50"
          onClick={generateTitles}
          disabled={loading || !content}>

                    Suggest Titles
                </button>
                <button
          className="px-6 py-2 bg-purple-600 hover:bg-purple-700 text-white font-semibold rounded-md transition-colors disabled:opacity-50"
          onClick={getSeoSuggestions}
          disabled={loading || !content}>
          
                    Get Suggestions
                </button>
            </div>

            {/* LOADING INDICATOR */}
            {loading &&
      <div className="mt-6 flex items-center gap-2 text-blue-400 animate-pulse">
                    <div className="w-2 h-2 bg-blue-400 rounded-full"></div>
                    <p>A.I.N.D.Y. is analyzing your content...</p>
                </div>
      }

            {/* RESULTS SECTIONS */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8">
                
                {/* SEO ANALYSIS BOX */}
                {seoData &&
        <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-xl shadow-lg">
                        <div className="flex items-center justify-between mb-4 border-b border-zinc-800 pb-2">
                            <h2 className="text-xl font-bold text-blue-400">SEO Scorecard</h2>
                            {seoData.search_score != null && (
                              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                                score {Math.round(Number(seoData.search_score) * 100)}
                              </span>
                            )}
                        </div>
                        <div className="space-y-2 text-gray-300">
                            {/* The verdict is always shown WITH the measurement, never instead
                                of it — a budget that hides the number is the tool deciding for
                                the writer (SEO_EDITING_AID_SPEC §2). */}
                            {seoData.title_analysis &&
                              <div className="mb-3 pb-3 border-b border-zinc-800" data-testid="title-analysis">
                                  <p>
                                      <strong className="text-white">Title:</strong>{" "}
                                      <span className={seoData.title_analysis.verdict === "long" ? "text-amber-400" : "text-emerald-400"}>
                                        {seoData.title_analysis.characters} characters
                                      </span>
                                      <span className="text-gray-500"> / {seoData.title_analysis.budget}</span>
                                      {seoData.title_analysis.over_by > 0 &&
                                        <span className="text-amber-400"> — {seoData.title_analysis.over_by} over</span>
                                      }
                                  </p>
                                  {seoData.title_analysis.truncated &&
                                    <p className="mt-1 text-sm text-gray-400">
                                        Shows as: <span className="italic text-gray-300">{seoData.title_analysis.serp_preview}</span>
                                    </p>
                                  }
                              </div>
                            }
                            <p><strong className="text-white">Word Count:</strong> {seoData.word_count}</p>
                            <p><strong className="text-white">Readability:</strong> <span className="text-emerald-400">{seoData.readability}</span></p>
                            <p><strong className="text-white">Top Keywords:</strong> {(seoData.top_keywords || []).join(", ")}</p>

                            <h3 className="mt-4 font-bold text-white">Keyword Densities:</h3>
                            <ul className="grid grid-cols-2 gap-2 mt-2">
                                {safeMap(Object.entries(seoData.keyword_densities || {}), ([keyword, density]) =>
              <li key={keyword} className="bg-zinc-800 p-2 rounded-sm text-sm border border-zinc-700">
                                        <span className="text-gray-400">{keyword}:</span> <span className="text-blue-300">{density}%</span>
                                    </li>)
              }
                            </ul>
                        </div>
                    </div>
        }

                {/* META DESCRIPTION BOX */}
                {metaDescription &&
        <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-xl shadow-lg">
                        <h2 className="text-xl font-bold mb-4 text-emerald-400 border-b border-zinc-800 pb-2">Meta Description</h2>
                        <p className="italic text-gray-300 leading-relaxed">"{metaDescription}"</p>
                        {metaCharacters != null &&
                          <p className="mt-2 text-xs text-gray-500" data-testid="meta-character-count">
                              {metaCharacters} characters — search results show about 160
                          </p>
                        }
                        <button
            className="mt-4 text-xs text-zinc-500 hover:text-white underline"
            onClick={() => navigator.clipboard.writeText(metaDescription)}>
            
                            Copy to clipboard
                        </button>
                    </div>
        }

                {/* TITLE OPTIONS — proposals, never a replacement. There is no "apply"
                    here on purpose: the writer copies the one they want into the field, or
                    ignores all of them. A tool that swaps the author's title for its own has
                    stopped being an editing aid (SEO_EDITING_AID_SPEC). */}
                {titleOptions &&
        <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-xl shadow-lg md:col-span-2" data-testid="title-options">
                        <h2 className="text-xl font-bold mb-1 text-amber-400 border-b border-zinc-800 pb-2">Title Options</h2>
                        <p className="text-xs text-gray-500 mb-4">
                            Suggestions only — copy one into the title field, or keep your own.
                        </p>
                        {titleOptions.candidates?.length ?
                          <ul className="space-y-2">
                              {safeMap(titleOptions.candidates, (candidate) =>
                                <li key={candidate.title} className="bg-zinc-800 p-3 rounded-sm border border-zinc-700">
                                    <p className="text-gray-200">{candidate.title}</p>
                                    <div className="mt-1 flex items-center gap-3 text-xs">
                                        <span className={candidate.over_by > 0 ? "text-amber-400" : "text-emerald-400"}>
                                          {candidate.characters} / {candidate.budget} characters
                                          {candidate.over_by > 0 ? ` — ${candidate.over_by} over` : ""}
                                        </span>
                                        <button
                                          className="text-zinc-500 hover:text-white underline"
                                          onClick={() => navigator.clipboard.writeText(candidate.title)}>
                                          Copy
                                        </button>
                                    </div>
                                </li>)
                              }
                          </ul>
                        :
                          <p className="text-gray-400" data-testid="title-options-reason">
                              No suggestions — {titleOptions.reason || "nothing was returned"}.
                          </p>
                        }
                    </div>
        }

                {/* SUGGESTIONS BOX */}
                {seoSuggestions &&
        <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-xl shadow-lg md:col-span-2">
                        <h2 className="text-xl font-bold mb-4 text-purple-400 border-b border-zinc-800 pb-2">Improvement Strategy</h2>
                        <p className="text-gray-300 whitespace-pre-wrap">{seoSuggestions}</p>
                    </div>
        }
            </div>

            <SearchHistory
        searchType="seo_analysis"
        title="Recent SEO Analyses"
        refreshToken={historyRefresh}
        onSelect={handleHistorySelect} />
        </div>);

}
