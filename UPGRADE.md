# Upgrade Plan — NASA Investigation v2.0

## Vision
Transform from a powerful but functional pipeline into an **intelligent, visually sophisticated, accessible** anomaly investigation platform.

## Upgrade Pillars

### 1. 🧠 AI Intelligence
- **Natural Language Query Engine** — ask questions like "show me bright features in Mars images" and get filtered results
- **Smart Anomaly Categorization** — auto-classify anomalies (crater, boulder, albedo, artifact, linear, irregular)
- **AI-Generated Summaries** — plain-language insights from pipeline runs and findings
- **Semantic Search** — search across all findings, descriptions, and metadata with intent matching
- **Vision LLM Integration** — per-anomaly visual reasoning using existing OpenRouter config

### 2. 🖼 Gallery Overhaul
- **Masonry Grid Gallery** — Pinterest-style responsive layout for source images
- **Lightbox Viewer** — full-featured image viewer with zoom, pan, annotations
- **Infinite Scroll** — smooth progressive loading of gallery items
- **Rich Metadata Display** — EXIF-like data, measurements, flags visible at a glance
- **Multi-View Cards** — one card shows all band variants side-by-side
- **Gallery Filters** — filter by body, band, verdict, polarity, score range, has-strip

### 3. 🎨 Visual Sophistication
- **Glassmorphism Cards** — frosted glass panels with depth
- **Micro-Animations** — smooth hover effects, entrance animations, loading transitions
- **Animated Charts** — Plotly-powered interactive charts (tooltips, zoom, pan)
- **Dark Sci-Fi Theme** — enhanced with glow effects, grid overlays, scan lines
- **Consistent Design System** — CSS variables, component patterns, spacing scale

### 4. 🔍 Data Explorer
- **Interactive Plotly Dashboards** — hover, zoom, pan on all charts
- **Map-Based Viewer** — plot anomalies on Mars/Moon map (Leaflet)
- **Cross-Reference Matrix** — see how anomalies relate across bands and observations
- **Data Export** — CSV/JSON export from any filtered view
- **Compare Mode** — side-by-side comparison of anomalies

### 5. ⚡ Performance
- **Lazy Loading** — all images load on demand via IntersectionObserver
- **Image Optimization** — responsive srcset, modern formats (WebP), compression
- **Client-Side Caching** — IndexedDB for filtered datasets
- **Virtual Scrolling** — for lists with 1000+ items
- **Streaming API** — pipeline progress updates via SSE

### 6. ♿ Ease of Access
- **Keyboard Navigation** — full keyboard support (arrows, enter, escape, /)
- **Focus Management** — visible focus indicators, focus traps in modals
- **ARIA Labels** — screen reader support for all interactive elements
- **Progressive Disclosure** — details expand on demand, not overwhelming upfront
- **Onboarding Tour** — first-visit guided tour of features
- **Responsive Design** — mobile-first, touch-friendly controls

## Implementation Order

### Phase 1 ✅ COMPLETE
1. `pipeline/intelligence.py` — NLP query engine + smart categorization + summaries + insights + LLM integration
2. `app/server.py` — 5 new AI API endpoints + /map route
3. `showcase/template.html` — Enhanced gallery v2 (masonry, lightbox, glassmorphism, AI widgets, category filters)

### Phase 2 ✅ COMPLETE
4. `app/static/index.html` — Premium dashboard v2 (glassmorphism, AI bar, insights panel, onboarding tour)
5. `site/map.html` — Interactive Leaflet map viewer
6. `packaging/nasa-fullstack.spec` — Updated for intelligence module bundle

### Phase 3 Preview (Future)
- Enhanced Plotly interactive charts replacing SVG
- Vision LLM per-anomaly analysis integration
- Smart summaries and insight generation enhancements
- Streaming pipeline progress updates
- Cross-reference matrix and compare mode
