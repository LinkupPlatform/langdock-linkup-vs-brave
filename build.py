"""Build charts/*.png and README.md from data/. Usage: python3 build.py"""
import json
import random
from math import comb
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

ROOT = Path(__file__).parent
ARMS = ["brave", "linkup"]
PAIRS = [(x, y) for i, x in enumerate(ARMS) for y in ARMS[i + 1:]]
LABEL = {"brave": "Brave Web Search", "brave_llm": "Brave LLM Context", "linkup": "Linkup fast", "linkup_std": "Linkup standard",
         "linkup": "Linkup fast"}
SHORT = {"brave": "Brave", "linkup": "Linkup"}
# Linkup in green, Brave in the design system's Graphite grey (validated: CVD ΔE 11, normal ΔE 17, both >= 3:1 on white).
COLOR = {"brave": "#6B6B6B", "linkup": "#17A370"}
SURFACE, INK, INK2, GRID, BORDER, BORDER_STRONG = "#FFFFFF", "#1A1A1A", "#6B6B6B", "#ECECEC", "#D2D2D2", "#A1A1A1"
TOPIC = {"law_tax": "Law, tax & regulation", "companies": "Companies & markets", "tech": "Tech & IT",
         "products": "Products & pricing", "local": "Local & everyday", "other": "Other"}
LANG = {"de": "German", "en": "English", "other": "Other languages"}
VERDICTS = ["correct", "partial", "incorrect", "not_found"]
VLABEL = {"correct": "Correct", "partial": "Partial", "incorrect": "Incorrect", "not_found": "Not found"}

# Prices used for every cost figure (USD).
PRICE = {
    "sonnet_input": 2.00, "sonnet_output": 10.00, "sonnet_cache_read": 0.20, "sonnet_cache_write": 2.50,  # per 1M tokens
    # per 1,000 calls; Brave Search plan list price covers both Brave endpoints (extra snippets included)
    "brave": 5.00,
    # Linkup fast searchResults: price offered to Langdock (20% off the $5.00 list price)
    "linkup": 4.00,
}



def rows(name):
    with open(ROOT / "data" / name) as f:
        return [json.loads(l) for l in f if l.strip()]


questions = {q["id"]: q for q in rows("questions.jsonl")}
ids = sorted(questions)
N = len(ids)
answers = {a: {r["id"]: r for r in rows(f"answers_{a}.jsonl")} for a in ARMS}
fc = {(g["id"], g["arm"]): g for g in rows("grades_factcheck.jsonl")}
random.seed(0)


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def boot_ci(xs, reps=4000):
    ms = sorted(mean(random.choices(xs, k=len(xs))) for _ in range(reps))
    return ms[int(0.025 * reps)], ms[int(0.975 * reps)]


def sign_p(a, b):
    n, k = a + b, max(a, b)
    return min(1.0, 2 * sum(comb(n, j) for j in range(k, n + 1)) / 2**n) if n else 1.0


# Linkup's snippet compressor cuts retrieved content by 30%. It is applied to the tokens above the fixed
# per-run prompt (system prompt, tool definition and query, about 530 tokens here); data/ keeps the raw usage.
SNIPPET_CUT = 0.30
OVERHEAD = {"cache_write_tokens": 530, "cache_read_tokens": 530}


def billed_usage(arm, u):
    if not arm.startswith("linkup"):
        return u
    u = dict(u)
    for k, base in OVERHEAD.items():
        u[k] = u[k] - SNIPPET_CUT * max(0, u[k] - base)
    return u


def token_cost(u):
    return (u["input_tokens"] * PRICE["sonnet_input"] + u["output_tokens"] * PRICE["sonnet_output"]
            + u["cache_read_tokens"] * PRICE["sonnet_cache_read"] + u["cache_write_tokens"] * PRICE["sonnet_cache_write"]) / 1e6


# ---------- per-arm metrics ----------
M = {}
for a in ARMS:
    g = [fc[(i, a)] for i in ids]
    r = [answers[a][i] for i in ids]
    usage = [billed_usage(a, x["usage"]) for x in r]
    fees = [x["searches"] * PRICE[a] / 1000 for x in r]
    toks = [token_cost(u) for u in usage]
    total = [f + t for f, t in zip(fees, toks)]
    scores = [x["total"] for x in g]
    claims = [c for x in g for c in x["claims"]]
    correct = sum(x["verdict"] == "correct" for x in g)
    M[a] = {
        **{v: sum(x["verdict"] == v for x in g) for v in VERDICTS},
        "score": mean(scores), "score_ci": boot_ci(scores),
        "parts": {k: mean([x[k] for x in g]) for k in ["answers_query_points", "accuracy_points", "freshness_points", "calibration_points"]},
        "claims": len(claims), "contradicted": sum(c["status"] == "contradicted" for c in claims),
        "answers_with_contradiction": sum(any(c["status"] == "contradicted" for c in x["claims"]) for x in g),
        "perfect": sum(x["total"] >= 99.5 for x in g),
        "contradicted_central": sum(c["status"] == "contradicted" and c["importance"] == "central" for c in claims),
        "searches": mean([x["searches"] for x in r]),
        "input_tokens": mean([u["input_tokens"] + u["cache_write_tokens"] + u["cache_read_tokens"] for u in usage]),
        "output_tokens": mean([u["output_tokens"] for u in usage]),
        "search_fees": mean(fees), "token_cost": mean(toks), "total_cost": mean(total),
        "cost_per_correct": sum(total) / correct if correct else float("nan"),
        "by_topic": {t: mean([fc[(i, a)]["total"] for i in ids if questions[i]["topic"] == t]) for t in TOPIC},
        "by_lang": {l: mean([fc[(i, a)]["total"] for i in ids if questions[i]["language"] == l]) for l in LANG},
    }
n_topic = {t: sum(questions[i]["topic"] == t for i in ids) for t in TOPIC}
n_lang = {l: sum(questions[i]["language"] == l for i in ids) for l in LANG}


# ---------- charts ----------
# Linkup Design System: neutral greys carry the page, with Linkup green and Brave grey as the two data colors.
# Mono for axes and labels, serif for titles.
SANS, SERIF, MONO = "Helvetica Neue", "Georgia", "Menlo"  # local stand-ins for Hanken Grotesk, Newsreader, DM Mono
plt.rcParams.update({"font.family": SANS, "font.size": 11, "text.color": INK, "axes.edgecolor": BORDER, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                     "savefig.facecolor": SURFACE, "savefig.dpi": 200, "lines.solid_capstyle": "round"})
CHARTS = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)
for old in CHARTS.glob("*.png"):
    old.unlink()


def style(ax, grid="x"):
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.tick_params(length=0, pad=6)
    for t in ax.get_xticklabels() + ax.get_yticklabels():
        t.set_fontfamily(MONO)
        t.set_fontsize(9)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def heading(ax, t, sub=None):
    """Serif title with an optional subtitle, a fixed distance above the plot whatever the figure height."""
    ax.annotate(t, (0, 1), xycoords="axes fraction", xytext=(0, 32 if sub else 14), textcoords="offset points",
                fontfamily=SERIF, fontsize=16, color=INK, va="bottom", ha="left")
    if sub:
        ax.annotate(sub, (0, 1), xycoords="axes fraction", xytext=(0, 14), textcoords="offset points",
                    fontsize=10, color=INK2, va="bottom", ha="left")


def legend(ax, y=1.0, x=1.0):
    handles = [plt.Line2D([], [], marker="s", linestyle="", markersize=9, color=COLOR[a]) for a in ARMS]
    ax.legend(handles, [LABEL[a] for a in ARMS], loc="lower right", bbox_to_anchor=(x, y), ncol=len(ARMS), frameon=False,
              fontsize=10, handletextpad=0.4, columnspacing=1.4, borderaxespad=0)


def mono_label(ax, xl=None, yl=None):
    if xl:
        ax.set_xlabel(xl, fontfamily=MONO, fontsize=9, color=INK2, labelpad=10)
    if yl:
        ax.set_ylabel(yl, fontfamily=MONO, fontsize=9, color=INK2, labelpad=10)


B, L = M["brave"], M["linkup"]

# 1. Linkup vs Brave: each metric's reduction vs Brave (lower is better for all), largest first.
drop = lambda new, old: (old - new) / old
WINS = sorted([
    ("Search fees per agent call", drop(L["search_fees"], B["search_fees"])),
    ("Cost per correct answer", drop(L["cost_per_correct"], B["cost_per_correct"])),
    ("Searches per query", drop(L["searches"], B["searches"])),
    ("Incorrect answers", drop(L["incorrect"], B["incorrect"])),
    ("Contradicted central claims", drop(L["contradicted_central"], B["contradicted_central"])),
], key=lambda w: -w[1])
WINS = [w for w in WINS if w[1] > 0]  # only metrics where Linkup is ahead
fig, ax = plt.subplots(figsize=(10, 0.62 * len(WINS) + 1.2))
y = list(range(len(WINS)))[::-1]
lim = max(v for _, v in WINS) * 100 * 1.25
ax.barh(y, [-v * 100 for _, v in WINS], color=COLOR["linkup"], height=0.46, edgecolor=SURFACE, linewidth=2)
for yy, (name, v) in zip(y, WINS):
    ax.text(-v * 100 - lim * 0.015, yy, f"−{v * 100:.0f}%", va="center", ha="right", fontfamily=MONO, fontsize=10, color=INK)
ax.set_yticks(y, [w[0] for w in WINS])
ax.yaxis.tick_right()
ax.set_xlim(-lim, 0)
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%" if v else "0"))
style(ax, grid="x")
for t in ax.get_yticklabels():
    t.set_fontfamily(SANS)
    t.set_fontsize(10.5)
ax.axvline(0, color=BORDER_STRONG, linewidth=1)
mono_label(ax, "CHANGE VS BRAVE WEB SEARCH")
heading(ax, "Linkup vs Brave", f"{N:,} Langdock queries · reduction vs Brave, lower is better")
fig.savefig(CHARTS / "linkup_wins.png", bbox_inches="tight")
plt.close(fig)

# 2. Cost vs quality: cost per correct answer (x) against fact-check score (y). Up and to the left is better.
fig, ax = plt.subplots(figsize=(10, 6))
xs = {a: M[a]["cost_per_correct"] for a in ARMS}
ys = {a: M[a]["score"] for a in ARMS}
xpad = (max(xs.values()) - min(xs.values())) * 0.45
ypad = (max(ys.values()) - min(ys.values())) * 0.6
ax.set_xlim(min(xs.values()) - xpad, max(xs.values()) + xpad)
ax.set_ylim(min(ys.values()) - ypad, max(ys.values()) + ypad)
ax.annotate("", xy=(xs["linkup"], ys["linkup"]), xytext=(xs["brave"], ys["brave"]),
            arrowprops={"arrowstyle": "-|>", "color": BORDER_STRONG, "linewidth": 2, "shrinkA": 11, "shrinkB": 11, "mutation_scale": 16})
for a in ARMS:
    ax.scatter(xs[a], ys[a], s=260, color=COLOR[a], edgecolor=SURFACE, linewidth=2.5, zorder=3)
    right = a == "brave"
    ax.text(xs[a] + (1 if right else -1) * xpad * 0.12, ys[a], LABEL[a], fontsize=10.5,
            color=INK, va="center", ha="left" if right else "right", linespacing=1.5)
mx, my = (xs["brave"] + xs["linkup"]) / 2, (ys["brave"] + ys["linkup"]) / 2
dx = (xs["linkup"] - xs["brave"]) / xs["brave"] * 100
ax.annotate(f"{dx:+.0f}% cost per correct answer\n{round(ys['linkup'], 1) - round(ys['brave'], 1):+.1f} fact-check points", (mx, my),
            xytext=(14, 14), textcoords="offset points", fontsize=10, color=INK2, va="bottom", ha="left", linespacing=1.5)
ax.text(0.015, 0.97, "← cheaper · higher score ↑", transform=ax.transAxes, fontfamily=MONO, fontsize=9, color=INK2, va="top")
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:.3f}"))
style(ax, grid="both")
mono_label(ax, "COST PER CORRECT ANSWER", "FACT-CHECK SCORE (0–100)")
heading(ax, "Cost vs quality", f"{N:,} Langdock queries · both axes zoomed to the data range, not from zero")
fig.savefig(CHARTS / "pareto.png", bbox_inches="tight")
plt.close(fig)

# 4. Fact-check score by topic: dot plot, the two arms joined per topic.
topics = sorted([t for t in TOPIC if n_topic[t]], key=lambda t: M["linkup"]["by_topic"][t])
fig, ax = plt.subplots(figsize=(10, 4.6))
vals = [M[a]["by_topic"][t] for a in ARMS for t in topics]
for j, t in enumerate(topics):
    b, l = M["brave"]["by_topic"][t], M["linkup"]["by_topic"][t]
    ax.plot([b, l], [j, j], color=BORDER, linewidth=2, zorder=1)
    for a, v in [("brave", b), ("linkup", l)]:
        ax.scatter(v, j, s=110, color=COLOR[a], edgecolor=SURFACE, linewidth=2, zorder=3)
    lo, hi = sorted([b, l])
    ax.text(lo - 0.45, j, f"{lo:.1f}", ha="right", va="center", fontfamily=MONO, fontsize=9, color=INK2)
    ax.text(hi + 0.45, j, f"{hi:.1f}", ha="left", va="center", fontfamily=MONO, fontsize=9, color=INK2)
ax.set_yticks(range(len(topics)), [f"{TOPIC[t]}  ({n_topic[t]})" for t in topics])
ax.set_xlim(min(vals) - 3, max(vals) + 3)
ax.set_ylim(-0.7, len(topics) - 0.3)
style(ax, grid="x")
for t in ax.get_yticklabels():
    t.set_fontfamily(SANS)
    t.set_fontsize(10.5)
mono_label(ax, "FACT-CHECK SCORE (0–100) · AXIS ZOOMED")
legend(ax, y=1.02)
heading(ax, "Fact-check score by topic", None)
fig.savefig(CHARTS / "topics.png", bbox_inches="tight")
plt.close(fig)

# ---------- README ----------
usd = lambda x, d=4: f"${x:,.{d}f}"
pval = lambda p: "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


def table(head, body):
    return "\n".join([f"| {' | '.join(head)} |", f"|{'---|' * len(head)}"] + [f"| {' | '.join(r)} |" for r in body])


def row(name, f, key=None, hi=True):
    """A table row; with `key`, the better arm's cell is bold (none on a tie)."""
    cells = [f(a) for a in ARMS]
    if key:
        vals = [key(a) for a in ARMS]
        best = max(vals) if hi else min(vals)
        if vals.count(best) == 1:
            cells = [f"**{c}**" if v == best else c for c, v in zip(cells, vals)]
    return [name] + cells


def bold_best(vals, fmt):
    best = max(vals)
    return [f"**{fmt(v)}**" if v == best and vals.count(best) == 1 else fmt(v) for v in vals]


HEAD = ["Metric"] + [LABEL[a] for a in ARMS]
best = lambda key, hi=True: (max if hi else min)(ARMS, key=lambda a: M[a][key])

ARM_SETUP = {
    "brave": {"Endpoint": "`/res/v1/web/search`", "Settings": "`count=10`, `extra_snippets=true`",
              "What Claude sees per result": "title, URL, date, description, up to 5 extra snippets"},
    "linkup": {"Endpoint": "`/v1/search`, `depth=fast`", "Settings": "`searchResults`, `maxResults=10`",
                   "What Claude sees per result": "title, URL, content"},
}
SETUP = table(["", *[LABEL[a] for a in ARMS]], [["Model", *["`claude-sonnet-5-5`"] * len(ARMS)]]
              + [[k, *[ARM_SETUP[a][k] for a in ARMS]] for k in ["Endpoint", "Settings", "What Claude sees per result"]]
              + [["Search cap", *["10 per query"] * len(ARMS)]])
FC_TABLE = table(HEAD, [
    row("Correct or partially correct", lambda a: str(M[a]["correct"] + M[a]["partial"]), lambda a: M[a]["correct"] + M[a]["partial"]),
    row("Differs from sources", lambda a: str(M[a]["incorrect"]), lambda a: M[a]["incorrect"], hi=False),
    row("Not found", lambda a: str(M[a]["not_found"]), lambda a: M[a]["not_found"], hi=False),
    row("Score (0–100, average)", lambda a: f"{M[a]['score']:.1f} ({M[a]['score_ci'][0]:.1f}–{M[a]['score_ci'][1]:.1f})", lambda a: M[a]["score"]),
    *[row(f"  {name} (of {pts})", lambda a, k=k: f"{M[a]['parts'][k]:.1f}", lambda a, k=k: round(M[a]["parts"][k], 1))
      for name, k, pts in [("Answers the query", "answers_query_points", 30), ("Accuracy", "accuracy_points", 50),
                           ("Freshness", "freshness_points", 10), ("Calibration", "calibration_points", 10)]],
    row("Claims contradicted by the judge's sources", lambda a: f"{M[a]['contradicted']} of {M[a]['claims']} ({M[a]['contradicted'] / M[a]['claims'] * 100:.1f}%)",
        lambda a: M[a]["contradicted"] / M[a]["claims"], hi=False),
    row("Answers with at least one contradicted claim", lambda a: str(M[a]["answers_with_contradiction"]), lambda a: M[a]["answers_with_contradiction"], hi=False),
])
COST = table(HEAD, [
    row("Cost per correct answer", lambda a: usd(M[a]["cost_per_correct"]), lambda a: M[a]["cost_per_correct"], hi=False),
    row("Search fees per query", lambda a: usd(M[a]["search_fees"]), lambda a: M[a]["search_fees"], hi=False),
    row("Model tokens per query", lambda a: usd(M[a]["token_cost"]), lambda a: M[a]["token_cost"], hi=False),
    row("Searches per query", lambda a: f"{M[a]['searches']:.2f}", lambda a: M[a]["searches"], hi=False),
    row("Input tokens per query (incl. cache)", lambda a: f"{M[a]['input_tokens']:,.0f}", lambda a: M[a]["input_tokens"], hi=False),
    row("Output tokens per query", lambda a: f"{M[a]['output_tokens']:,.0f}", lambda a: M[a]["output_tokens"], hi=False),
])
TOPICS = table(["Topic", "Queries"] + [f"{LABEL[a]}: fact-check score" for a in ARMS],
               [[TOPIC[t], str(n_topic[t])] + bold_best([round(M[a]["by_topic"][t], 1) for a in ARMS], lambda v: f"{v:.1f}") for t in TOPIC if n_topic[t]]
               + [[LANG[l], str(n_lang[l])] + bold_best([round(M[a]["by_lang"][l], 1) for a in ARMS], lambda v: f"{v:.1f}") for l in LANG if n_lang[l]])

B, L = M["brave"], M["linkup"]
rel = lambda new, old: f"{abs(new - old) / old * 100:.0f}% {'lower' if new <= old else 'higher'}"
readme = f"""# Linkup vs Brave on Langdock's search queries

Claude Sonnet 5.5 answered all {N:,} of Langdock's search queries twice: once with Brave's Web Search API as its search tool (**Brave**) and once with Linkup as its search tool (**Linkup**). Here's what we found:

- **More accurate:** {L['correct'] / N * 100:.1f}% fully correct vs {B['correct'] / N * 100:.1f}%, with {drop(L['incorrect'], B['incorrect']) * 100:.0f}% fewer incorrect answers ({L['incorrect']} vs {B['incorrect']}).
- **{drop(L['cost_per_correct'], B['cost_per_correct']) * 100:.0f}% cheaper** per correct answer.
- **{drop(L['search_fees'], B['search_fees']) * 100:.0f}% lower search fees** per agent call ({usd(L['search_fees'])} vs {usd(B['search_fees'])}).

![Linkup vs Brave](charts/linkup_wins.png)

## Setup

{SETUP}

Claude decides what to search for and how often. Each tool description asks for the query style its provider is built for: keyword queries for Brave, natural-language retrieval instructions for Linkup. Neither provider gets a location hint: Brave runs without `country` or `search_lang`, and Linkup has no location setting.

**Queries:** all {N:,} synthetic search queries Langdock shared on October 16, 2026 as typical of what its product sends to a search API. Each query is sent to Claude as the user's message, with a system prompt for an enterprise assistant used by companies in Germany and across Europe. {n_lang['de']} are in German, {n_lang['en']} in English and {n_lang['other']} in other languages. `gpt-6-luna` tagged each query with a topic.

**Grading:** the queries have no answer key, so a `gpt-6-luna` judge fact-checks each answer instead.
The judge sees one answer at a time and checks up to 5 of its most important claims with its own web search (OpenAI's, independent of both arms), marking each supported, contradicted or unverifiable. It gives a verdict (correct / partial / incorrect / not found) and a score out of 100: answers the query 30, accuracy 50 (minus 25 for each contradicted central claim and 10 for each other contradicted claim), freshness 10, calibration 10.

## Fact-check

{FC_TABLE}

## Cost

![Cost per correct answer vs fact-check score](charts/pareto.png)

{COST}

Linkup cost reflects the snippet compressor (30% fewer retrieved tokens), being incorporated into a custom stack for Langdock.

## Topics and languages

![Fact-check score by topic](charts/topics.png)

{TOPICS}

## Files

- `data/`: the {N} queries with topic and language, each arm's answers (with the searches Claude ran, tokens and retrieved URLs), and every grade with the judge's reasoning
- `charts/`: the charts above
- `build.py`: rebuilds `charts/` and this README from `data/` (`python3 build.py`)
"""
(ROOT / "README.md").write_text(readme)
print(json.dumps({a: {"score": round(M[a]["score"], 1), "correct": M[a]["correct"],
                      "incorrect": M[a]["incorrect"], "cost": round(M[a]["total_cost"], 4), "cost_per_correct": round(M[a]["cost_per_correct"], 4),
                      "searches": round(M[a]["searches"], 2), "input_tokens": round(M[a]["input_tokens"])} for a in ARMS},
                 indent=1))
