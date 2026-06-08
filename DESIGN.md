# Perf Coach — Design Reference

## Color Tokens

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

## Typography

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
