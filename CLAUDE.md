# perf-coach

A personal performance dashboard. Tracks weight, habits, and other metrics.

## Stack

- Static HTML, CSS, vanilla JavaScript
- No backend yet — mock data lives in `js/mock-data.js` when needed
- Charting library to use: Chart.js via CDN (no build step)

## Project Structure

    index.html        Landing page
    weight.html       Weight tracking and chart
    habits.html       Habit tracker (todo-style)
    css/styles.css    Shared styles
    js/               Page-specific JS modules
    js/env.js         Detects UAT vs PRD environment
    js/mock-data.js   Mock data for charts (no backend)

## Conventions

- Vanilla JS only — no frameworks, no bundlers
- Use modern browser APIs (fetch, localStorage if needed)
- Each HTML page loads only the JS it needs
- One CSS file shared across pages
- Mock data is hardcoded in JS files clearly marked `// MOCK`
- Env detection: hostname/port indicates UAT vs PRD

## Branching

- master = production
- develop = integration
- feature/<N>-<slug> = work branches off develop
