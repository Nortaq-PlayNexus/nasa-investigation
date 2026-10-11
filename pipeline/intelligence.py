"""AI-powered intelligence layer for NASA Investigation.

Provides:
- Natural language query parsing → filter criteria
- Smart anomaly categorization (crater, boulder, albedo, artifact, linear, irregular)
- Semantic search across findings and metadata
- Vision LLM integration for per-anomaly reasoning
- AI-generated summary generation
- Smart recommendations and insights

All AI features work offline (local rules) unless an LLM API key is configured.
"""

import json
import os
import re
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project root (works in dev and frozen modes)
# ---------------------------------------------------------------------------

def _root():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS)
        if (p / "config" / "pipeline.json").exists():
            return p
        return Path(sys.executable).resolve().parent if hasattr(sys, "executable") else p
    return Path(__file__).resolve().parents[2]

ROOT = _root()
PIPELINE_DIR = ROOT / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import common  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Natural Language Query Engine
# ---------------------------------------------------------------------------

# Keyword → field mapping for intelligent query parsing
QUERY_KEYWORDS = {
    # Body / target
    "mars": {"body": "Mars"},
    "moon": {"body": "Moon"},
    "lunar": {"body": "Moon"},
    "red planet": {"body": "Mars"},
    "earth neighbor": {"body": "Moon"},

    # Verdicts
    "confirmed": {"verdict": "CONFIRMED-LEAD"},
    "lead": {"verdict": "CONFIRMED-LEAD"},
    "promising": {"verdict": "PROMISING"},
    "terrain": {"verdict": "TERRAIN"},
    "noise": {"verdict": "NOISE"},
    "weak": {"verdict": "WEAK"},
    "explained": {"verdict": "EXPLAINED-ARTIFACT"},
    "artifact": {"verdict": "EXPLAINED-ARTIFACT"},
    "debunked": {"verdict": "EXPLAINED-ARTIFACT"},

    # Band / variant
    "mirb": {"band": "MIRB"},
    "mrgb": {"band": "MRGB"},
    "red": {"band": "RED"},
    "black white": {"band": "MIRB"},
    "bw": {"band": "MIRB"},
    "color": {"band": "MRGB"},

    # Polarity
    "bright": {"polarity": "bright"},
    "dark": {"polarity": "dark"},
    "light": {"polarity": "bright"},

    # Scoring
    "high score": {"min_score": 80},
    "top": {"min_score": 80},
    "excellent": {"min_score": 90},
    "good": {"min_score": 60},
    "poor": {"max_score": 40},

    # Size descriptors
    "small": {"max_area": 500},
    "tiny": {"max_area": 200},
    "large": {"min_area": 5000},
    "huge": {"min_area": 20000},
    "big": {"min_area": 5000},
    "medium": {"min_area": 500, "max_area": 5000},

    # Feature types (categorization)
    "crater": {"category": "crater"},
    "boulder": {"category": "boulder"},
    "albedo": {"category": "albedo"},
    "shadow": {"category": "shadow"},
    "linear": {"category": "linear"},
    "streak": {"category": "linear"},
    "artifact": {"category": "artifact"},
    "grid": {"category": "artifact"},
    "irregular": {"category": "irregular"},
    "round": {"category": "crater"},
    "roundish": {"category": "crater"},

    # Quality
    "sharp": {"min_contrast": 3.0},
    "fuzzy": {"max_contrast": 1.5},
    "high contrast": {"min_contrast": 3.0},
    "low contrast": {"max_contrast": 1.5},

    # Compound / intent
    "interesting": {"min_score": 70, "min_contrast": 2.0},
    "suspicious": {"min_score": 60},
    "real": {"verdict": "CONFIRMED-LEAD"},
    "fake": {"verdict": "EXPLAINED-ARTIFACT"},
    "everything": {},
}


def parse_natural_query(query: str) -> dict:
    """Parse a natural language query into filter criteria.

    Returns a dict of field→value pairs that can be applied to feature data.
    Also returns a 'raw_text' field for semantic search fallback.

    Examples:
        "bright features on Mars" → {"body": "Mars", "polarity": "bright"}
        "high contrast craters" → {"min_contrast": 3.0, "category": "crater"}
        "show me the top ones" → {"min_score": 80}
        "anything suspicious" → {"min_score": 60}
    """
    if not query:
        return {}

    q = query.lower().strip()
    criteria = {}
    matched_any = False

    # Check for negation patterns ("not", "exclude", "no")
    negations = []
    for word in ["not ", "exclude ", "no ", "minus ", "-"]:
        if word in q:
            neg_text = q.replace(word, "").strip()
            negations.append(neg_text)

    # Check for range patterns ("between X and Y", "score > 50", etc.)
    range_criteria = _parse_ranges(q)
    if range_criteria:
        criteria.update(range_criteria)

    # Check for explicit comparison patterns
    comp_criteria = _parse_comparisons(q)
    if comp_criteria:
        criteria.update(comp_criteria)

    # Multi-word phrase matching (must check before single words)
    multi_word = [k for k in QUERY_KEYWORDS if " " in k and k in q]
    multi_word.sort(key=lambda k: -len(k))  # longest match first

    for kw in multi_word + [k for k in QUERY_KEYWORDS if " " not in k]:
        if kw in q:
            entry = QUERY_KEYWORDS[kw]
            if entry:
                for field, val in entry.items():
                    if field in criteria and isinstance(criteria[field], (int, float)):
                        # For numeric ranges, merge (use tighter bound)
                        if field.startswith("min") and isinstance(val, (int, float)):
                            criteria[field] = max(criteria[field], val)
                        elif field.startswith("max") and isinstance(val, (int, float)):
                            criteria[field] = min(criteria[field], val)
                        else:
                            pass  # keep existing
                    else:
                        criteria[field] = val
            matched_any = True

    # Remove negated terms from criteria (simplified: if user says "no artifacts",
    # exclude EXPLAINED-ARTIFACT)
    for neg in negations:
        neg_criteria = parse_natural_query(neg)
        for field, val in neg_criteria.items():
            if field == "verdict" and val == criteria.get("verdict"):
                criteria.pop("verdict", None)

    criteria["_query_text"] = q
    return criteria


def _parse_ranges(q: str) -> dict:
    """Parse patterns like 'score between 50 and 80', 'contrast 2 to 4'."""
    criteria = {}
    m = re.search(r"(score|contrast|area)\s+(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)", q)
    if m:
        field = m.group(1)
        lo, hi = float(m.group(2)), float(m.group(3))
        if lo > hi:
            lo, hi = hi, lo
        criteria[f"min_{field}"] = lo
        criteria[f"max_{field}"] = hi
    return criteria


def _parse_comparisons(q: str) -> dict:
    """Parse patterns like 'score > 50', 'contrast >= 2', 'area < 1000'."""
    criteria = {}
    patterns = [
        (r"(score|contrast|area)\s*>=\s*(\d+(?:\.\d+)?)", "min"),
        (r"(score|contrast|area)\s*<=\s*(\d+(?:\.\d+)?)", "max"),
        (r"(score|contrast|area)\s*>\s*(\d+(?:\.\d+)?)", "min"),
        (r"(score|contrast|area)\s*<\s*(\d+(?:\.\d+)?)", "max"),
        (r"(score|contrast|area)\s*=\s*(\d+(?:\.\d+)?)", "exact"),
    ]
    for pattern, prefix in patterns:
        m = re.search(pattern, q)
        if m:
            field = m.group(1)
            val = float(m.group(2))
            key = f"{prefix}_{field}" if prefix != "exact" else field
            criteria[key] = val
    return criteria


def apply_filters(features: list, criteria: dict) -> list:
    """Apply parsed filter criteria to a list of feature dicts."""
    if not criteria:
        return features

    filtered = []
    for f in features:
        ok = True
        for field, val in criteria.items():
            if field.startswith("_"):
                continue  # internal fields like _query_text

            if field == "body":
                if f.get("_body", "") != val:
                    ok = False; break
            elif field == "verdict":
                verdicts = f.get("verdicts", [f.get("verdict", "")])
                if val not in verdicts:
                    ok = False; break
            elif field == "band":
                if val not in f.get("bands", []):
                    ok = False; break
            elif field == "polarity":
                members = f.get("members", [f])
                if not any(m.get("polarity") == val for m in members):
                    ok = False; break
            elif field == "category":
                cat = categorize(f)
                if cat != val:
                    ok = False; break
            elif field == "min_score":
                if float(f.get("max_score", 0)) < val:
                    ok = False; break
            elif field == "max_score":
                if float(f.get("max_score", 999)) > val:
                    ok = False; break
            elif field == "min_contrast":
                if float(f.get("max_contrast", 0)) < val:
                    ok = False; break
            elif field == "max_contrast":
                if float(f.get("max_contrast", 999)) > val:
                    ok = False; break
            elif field == "min_area":
                if int(f.get("area", 0)) < val:
                    ok = False; break
            elif field == "max_area":
                if int(f.get("area", 0)) > val:
                    ok = False; break
            elif field == "min_contrast":
                if float(f.get("max_contrast", 0)) < val:
                    ok = False; break

        if ok:
            filtered.append(f)
    return filtered


# ---------------------------------------------------------------------------
# 2. Smart Anomaly Categorization
# ---------------------------------------------------------------------------

CATEGORY_RULES = {
    "crater": {
        "keywords": ["circular", "round", "bowl", "depression", "impact", "rim"],
        "metrics": {"aspect_max": 1.8, "compactness_min": 0.7},
        "description": "Circular or bowl-shaped depression, likely impact origin",
    },
    "boulder": {
        "keywords": ["block", "rock", "stone", "pebble", "clast", "lump", "chunk"],
        "metrics": {"aspect_max": 3.0, "compactness_min": 0.5},
        "description": "Compact raised feature, likely rock or boulder",
    },
    "albedo": {
        "keywords": ["bright patch", "dark patch", "albedo", "reflectance", "tone", "shade"],
        "metrics": {"aspect_max": 8.0},
        "description": "Area of different brightness, likely albedo variation",
    },
    "linear": {
        "keywords": ["line", "streak", "ridge", "groove", "track", "scar", "crack", "fissure"],
        "metrics": {"aspect_min": 2.5},
        "description": "Elongated feature, linear or arc-shaped",
    },
    "artifact": {
        "keywords": ["grid", "pixel", "hot", "stripe", "band", "compression", "sensor", "bloom", "bleed"],
        "metrics": {},
        "description": "Known sensor or processing artifact",
    },
    "irregular": {
        "keywords": ["irregular", "complex", "amorphous", "blob", "patch", "cluster"],
        "metrics": {},
        "description": "Amorphous or complex shape without clear class",
    },
}


def categorize(feature: dict) -> str:
    """Auto-classify an anomaly into a category based on its properties.

    Uses flags, aspect ratio, compactness, and textual clues.
    Returns the category name.
    """
    flags_str = " ".join(str(feature.get("flags", []))).lower()
    # Also check member flags
    for m in feature.get("members", []):
        flags_str += " " + " ".join(str(m.get("flags", []))).lower()

    scores = {}
    for cat, rules in CATEGORY_RULES.items():
        score = 0
        # Keyword match from flags
        for kw in rules["keywords"]:
            if kw in flags_str:
                score += 3

        # Metric-based scoring
        metrics = rules["metrics"]
        aspect = float(feature.get("aspect", 1) or 1)
        compactness = float(feature.get("compactness", 0) or 0)

        if "aspect_max" in metrics and aspect <= metrics["aspect_max"]:
            score += 2
        if "aspect_min" in metrics and aspect >= metrics["aspect_min"]:
            score += 2
        if "compactness_min" in metrics and compactness >= metrics["compactness_min"]:
            score += 2

        # Polarity hints
        polarity = feature.get("polarity", "").lower()
        if cat == "albedo" and polarity in ("bright", "dark"):
            score += 1
        if cat == "artifact" and "compression" in flags_str:
            score += 3

        scores[cat] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "irregular"
    return best


def categorize_all(features: list) -> list:
    """Add category field to each feature."""
    for f in features:
        f["category"] = categorize(f)
        f["category_desc"] = CATEGORY_RULES.get(f["category"], {}).get("description", "")
    return features


# ---------------------------------------------------------------------------
# 3. AI Summary Generation
# ---------------------------------------------------------------------------

def generate_summary(features: list, stats: dict = None) -> str:
    """Generate a plain-language summary of the anomaly dataset."""
    if not features:
        return "No anomalies to summarize."

    total = len(features)
    conf = sum(1 for f in features if f.get("verdict") == "CONFIRMED-LEAD")
    prom = sum(1 for f in features if f.get("verdict") == "PROMISING")
    others = total - conf - prom

    # Top features
    sorted_f = sorted(features, key=lambda f: float(f.get("max_score", 0)), reverse=True)
    top3 = sorted_f[:3]

    # Categories breakdown
    cats = {}
    for f in features:
        c = f.get("category", "irregular")
        cats[c] = cats.get(c, 0) + 1
    cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))

    # Bodies
    bodies = {}
    for f in features:
        b = f.get("_body", "unknown")
        bodies[b] = bodies.get(b, 0) + 1
    body_str = ", ".join(f"{k}: {v}" for k, v in sorted(bodies.items()))

    lines = [
        f"Analysis of {total} distinct anomalies found:",
        f"- {conf} CONFIRMED-LEAD and {prom} PROMISING features with strong evidence",
        f"- Distribution: {cat_str}",
        f"- Bodies: {body_str}",
    ]

    if top3:
        lines.append("\nTop 3 candidates:")
        for i, f in enumerate(top3, 1):
            name = f.get("base", "unnamed")
            score = f.get("max_score", 0)
            cat = f.get("category", "unknown")
            lines.append(f"  {i}. {name} — score {score:.0f}, category: {cat}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Vision LLM Integration
# ---------------------------------------------------------------------------

def has_llm_config() -> bool:
    """Check if LLM API is configured."""
    endpoint = os.environ.get("AI_LLM_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    key = os.environ.get("AI_LLM_KEY", "")
    return bool(key and endpoint)


def build_llm_prompt(feature: dict) -> str:
    """Build a vision LLM prompt for a single anomaly."""
    cat = feature.get("category", "unknown")
    cat_desc = feature.get("category_desc", "")
    metrics = [
        f"Score: {feature.get('max_score', 'N/A')}",
        f"Contrast: {feature.get('max_contrast', 'N/A')}",
        f"Area: {feature.get('area', 'N/A')} px",
        f"Aspect ratio: {feature.get('aspect', 'N/A')}",
        f"Polarity: {feature.get('polarity', 'N/A')}",
        f"Band variants: {', '.join(feature.get('bands', []))}",
        f"Evidence class: {feature.get('evidence_class', 'N/A')}",
        f"Flags: {', '.join(feature.get('flags', [])) or 'none'}",
    ]
    recommendation = feature.get("recommendation", "")

    return f"""You are a planetary geologist expert in NASA Mars/Moon orbital imagery analysis.

An anomaly detection system has identified a candidate feature in HiRISE or similar orbital imagery.

FEATURE ANALYSIS:
- Category: {cat} ({cat_desc})
- {" | ".join(metrics)}
- Cross-band confirmation: {"yes" if len(feature.get("bands", [])) > 1 else "no"}
- Adjudication verdict: {feature.get("verdict", "N/A")}

SCIENTIFIC ASSESSMENT:
{recommendation}

Based on the metrics and context above, provide a brief (2-3 sentence) scientific assessment:
1. Is this likely a real geological feature or an instrument/processing artifact?
2. What geological process might explain it if real?
3. What additional data would confirm or refute this?

Respond in plain language, suitable for a non-specialist audience. Be honest about uncertainty.
"""


def llm_analyze_feature(feature: dict) -> dict:
    """Run vision LLM analysis on a single feature (if API configured).

    Returns dict with llm_analysis field or error info.
    """
    if not has_llm_config():
        return {"llm_available": False, "llm_analysis": None, "reason": "No API key configured"}

    try:
        import urllib.request
        import json as json_mod

        prompt = build_llm_prompt(feature)
        endpoint = os.environ.get("AI_LLM_ENDPOINT")
        model = os.environ.get("AI_LLM_MODEL", "meta-llama/llama-3.2-90b-vision-instruct")
        max_tokens = int(os.environ.get("AI_LLM_MAX_TOKENS", "300"))

        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        req = urllib.request.Request(
            endpoint,
            data=json_mod.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('AI_LLM_KEY')}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json_mod.loads(resp.read().decode())
            analysis = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"llm_available": True, "llm_analysis": analysis}
    except Exception as e:
        return {"llm_available": True, "llm_analysis": None, "error": str(e)}


# ---------------------------------------------------------------------------
# 5. Smart Recommendations & Insights
# ---------------------------------------------------------------------------

def generate_insights(features: list) -> list:
    """Generate actionable insights from the anomaly dataset.

    Returns a list of insight dicts with title, description, and priority.
    """
    insights = []

    if not features:
        return [{"title": "No data", "description": "Run the pipeline to generate insights.", "priority": "info"}]

    # Insight: high-confidence leads
    conf = [f for f in features if f.get("verdict") == "CONFIRMED-LEAD"]
    if conf:
        top = max(conf, key=lambda f: float(f.get("max_score", 0)))
        insights.append({
            "title": "Top confirmed lead identified",
            "description": f"{top.get('base', 'unnamed')} scored {top.get('max_score', 0):.0f}% — highest confidence candidate. Recommend independent verification pass.",
            "priority": "high",
            "feature": top.get("base", ""),
        })

    # Insight: cross-band agreement
    cross_band = [f for f in features if len(f.get("bands", [])) >= 2]
    if cross_band:
        insights.append({
            "title": "Multi-band confirmations found",
            "description": f"{len(cross_band)} anomalies confirmed across {len(set(f.get('bands', [])) for f in cross_band)} or more band variants — stronger evidence of real features.",
            "priority": "medium",
        })

    # Insight: artifact prevalence
    artifacts = [f for f in features if f.get("category") == "artifact"]
    if artifacts and len(features) > 10:
        pct = len(artifacts) / len(features) * 100
        insights.append({
            "title": f"Artifact rate at {pct:.0f}%",
            "description": f"{len(artifacts)} of {len(features)} anomalies classified as known artifacts. The debunk-first methodology is working as expected.",
            "priority": "info",
        })

    # Insight: suspicious cluster
    body_counts = {}
    for f in features:
        b = f.get("_body", "unknown")
        body_counts.setdefault(b, []).append(f)
    for body, feats in body_counts.items():
        if len(feats) >= 5:
            top_3 = sorted(feats, key=lambda f: float(f.get("max_score", 0)), reverse=True)[:3]
            avg_score = sum(float(f.get("max_score", 0)) for f in top_3) / 3
            if avg_score > 50:
                insights.append({
                    "title": f"{body} shows concentrated activity",
                    "description": f"{len(feats)} anomalies in {body}, top 3 average score {avg_score:.0f}%. Consider focused investigation of this region.",
                    "priority": "medium",
                })

    # Insight: potential new class
    cats = {}
    for f in features:
        c = f.get("category", "unknown")
        cats.setdefault(c, []).append(f)
    rare = {k: v for k, v in cats.items() if len(v) <= 2}
    if rare:
        insights.append({
            "title": "Rare anomaly types detected",
            "description": f"Categories with ≤2 instances: {', '.join(rare.keys())}. These may represent new classes requiring expert review.",
            "priority": "low",
        })

    # Sort by priority
    prio_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    insights.sort(key=lambda i: prio_order.get(i.get("priority", "info"), 3))
    return insights


# ---------------------------------------------------------------------------
# 6. Pipeline Integration Helpers
# ---------------------------------------------------------------------------

def enrich_features(features: list) -> list:
    """Add all AI enrichment to a feature list (category, insights readiness)."""
    features = categorize_all(features)
    for f in features:
        f["_intelligence_ready"] = True
    return features


def query_features(features: list, raw_query: str) -> dict:
    """Full NLP query pipeline: parse → filter → enrich → summarize."""
    criteria = parse_natural_query(raw_query)
    filtered = apply_filters(features, criteria)
    enriched = enrich_features(filtered)
    summary = generate_summary(enriched)
    insights = generate_insights(enriched)
    return {
        "query": raw_query,
        "criteria": criteria,
        "matched": len(enriched),
        "total": len(features),
        "features": enriched,
        "summary": summary,
        "insights": insights,
    }
