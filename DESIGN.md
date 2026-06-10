# Perf Coach — Design Reference

## Gradient Design System (Home, Weight — current standard)

The home page and weight page use a gradient design language. New pages should follow this system.

### Gradient Background Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-1` | `#5a8dee` | Gradient start (top-left, light blue) |
| `--bg-2` | `#1f3b8a` | Gradient end (bottom-right, deep navy) |
| `--shell-1` | `#eaf0fb` | Nav bar top |
| `--shell-2` | `#d8e3f5` | Nav bar bottom |
| `--page-bg` | `radial-gradient(ellipse at top left, var(--bg-1) 0%, var(--bg-2) 70%)` | Full-page gradient background |

### Card Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--card-bg` | `#ffffff` | Floating card surface |
| `--card-border` | `rgba(13, 30, 67, 0.06)` | Subtle card border |
| `--card-radius` | `14px` | Card border-radius |
| `--card-shadow` | `0 2px 12px rgba(13,30,67,0.10), 0 1px 3px rgba(13,30,67,0.06)` | Soft card drop shadow |

### Text Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#0b1530` | Body text on white cards |
| `--text-secondary` | `#5c6886` | Secondary / muted text |
| `--text-tertiary` | `#8b95ad` | Labels, micro-text |

### Typography

- **Body / labels**: `Inter Tight` (Google Fonts) — `font-weight` 400/500/600/700
- **Numeric values** (weights, scores, metrics): `JetBrains Mono` (Google Fonts) — `font-weight` 500/600
- **Letter-spacing**: `-0.01em` (body), `-0.025em` (hero headings), `-0.04em` (large numerics)
- Load via: `https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap`

### Semantic Color Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--green` | `#2d5e10` | Positive delta text |
| `--green-soft` | `#dff5d6` | Green pill background |
| `--red` | `#7a1a1a` | Negative delta text |
| `--red-soft` | `#ffd9d9` | Red pill background |
| `--amber` | `#6b4408` | Warning text |
| `--amber-soft` | `#fff0c4` | Amber pill background |
| `--accent` | `#e4ff52` | Lime accent (CTA on dark) |

---

## Legacy Light Theme Tokens (Admin, Login, Settings)

These pages retain the older light-theme style. Do not mix with gradient-system pages.

## Color Tokens (legacy)

| Token | Value | Usage |
|-------|-------|-------|
| `--primary` | `#3b82f6` | Primary actions, active states |
| `--primary-dark` | `#2563eb` | Hover on primary |
| `--success` | `#16a34a` | Positive trends, done states |
| `--warning` | `#d97706` | Amber warnings, moderate load |
| `--danger` | `#dc2626` | Errors, high load, failed |
| `--text` | `#111827` | Body text |
| `--text-sub` | `#6b7280` | Secondary / muted text |
| `--border` | `#e5e7eb` | Dividers, card borders |
| `--surface` | `#ffffff` | Card / panel background |
| `--surface-2` | `#f9fafb` | Page background, alternate rows |
| `--readiness-high` | `#16a34a` | Readiness ≥ 70 |
| `--readiness-mid` | `#d97706` | Readiness 40–69 |
| `--readiness-low` | `#dc2626` | Readiness < 40 |

## Typography (legacy)

- **Font family**: system-ui, -apple-system, sans-serif
- **Base size**: 14px
- **Scale**: 11px (micro) · 12px (small) · 13px (body-sm) · 14px (body) · 16px (lg) · 20px (xl) · 24px (2xl)
- **Weight**: 400 (body), 500 (label/medium), 600 (heading), 700 (bold metric)
- **Headings**: `font-size: 1.25rem; font-weight: 600; margin-bottom: 0.5rem`
- **Card titles**: `font-size: 0.875rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em`

## Spacing Scale

| Token | Value |
|-------|-------|
| `4px` | xs — icon gap, tight inline |
| `8px` | sm — input padding, chip gap |
| `12px` | md — card inner padding compact |
| `16px` | base — card padding, section gap |
| `24px` | lg — between cards |
| `32px` | xl — page section gap |
| `48px` | 2xl — major section break |

## Layout

- **Page max-width**: 1280px, centred
- **Grid**: 12-column, 16px gutters; cards span 3–6 cols on desktop, full-width mobile
- **Card**: `border-radius: 8px; border: 1px solid var(--border); padding: 16px; background: var(--surface)`
- **Sidebar nav**: 220px fixed left; collapses to icon-only on mobile

## Component Naming Conventions

- BEM-lite: `block-element--modifier` e.g. `readiness-card`, `readiness-card__score`, `readiness-card--loading`
- JS state classes: `is-active`, `is-loading`, `is-empty`, `is-error`
- Utility prefix: `u-hidden`, `u-sr-only`
- Page-scoped prefix matches route: `home-*`, `training-log-*`, `trends-*`, `calendar-*`, `weight-*`

## Chart Conventions

- Library: Chart.js (CDN)
- Grid lines: `rgba(0,0,0,0.06)`, no x-axis grid
- Tooltip: dark background `#1f2937`, white text, 12px, rounded 4px
- Line charts: `tension: 0.3`, point radius 3 on hover only
- Area fill: 15% opacity of stroke color

## Responsive Breakpoints

| Name | Width |
|------|-------|
| mobile | < 640px |
| tablet | 640px – 1024px |
| desktop | ≥ 1024px |
