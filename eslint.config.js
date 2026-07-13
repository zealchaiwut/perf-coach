// ESLint v9 flat config — lints the vanilla JS frontend modules (issue #1355).
// HTML files are intentionally excluded; only *.js under frontend/ is in scope.
export default [
  {
    ignores: ["**/*.html"],
  },
  {
    files: ["frontend/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        fetch: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        localStorage: "readonly",
        location: "readonly",
        history: "readonly",
        navigator: "readonly",
        Chart: "readonly",
        URLSearchParams: "readonly",
        AbortController: "readonly",
        confirm: "readonly",
        alert: "readonly",
        CustomEvent: "readonly",
        Event: "readonly",
        FormData: "readonly",
        URL: "readonly",
        getComputedStyle: "readonly",
        requestAnimationFrame: "readonly",
        cancelAnimationFrame: "readonly",
        EventSource: "readonly",
      },
    },
    rules: {},
  },
];
