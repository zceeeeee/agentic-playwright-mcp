# Explore Explicit URL Navigation Design

## Goal

When an Explore-mode task contains an explicit `http://` or `https://` URL,
open that URL before taking any Explore snapshot or planning page actions.

For example:

```text
"https://ncesnext.com/"搜索大物
```

must navigate directly to:

```text
https://ncesnext.com/
```

and then continue the search through the normal Explore planner.

## Priority

An explicit URL supplied by the user has the highest entry-page priority in
Explore mode. It overrides:

- `about:blank`
- the currently open browser page
- known-platform entry inference
- LLM entry-page resolution
- search-engine entry fallback

This behavior is limited to Explore-mode fallback. Registered skills keep
control of their own navigation.

## Navigation Rules

1. Extract the first valid `http://` or `https://` URL from the task.
2. Before returning the `llm_explore` route, compare it with the current page.
3. If the normalized current URL differs, navigate to the explicit URL.
4. Mark the task as having completed its explicit entry navigation.
5. Return to `OBSERVE`, then continue directly in Explore mode.
6. Do not navigate again for the same task.
7. If the browser is already on the same normalized URL, do not refresh it;
   still activate Explore mode and proceed to observation.

URL comparison ignores an otherwise insignificant trailing slash and URL
fragment, while preserving paths and query parameters.

## Failure Handling

If the explicit URL cannot be opened, log the navigation error and allow the
existing Explore failure path to report that the task could not proceed. Do
not replace the user URL with a search engine or an LLM-inferred site.

## Testing

Regression coverage must verify:

- an explicit URL opens from `about:blank`
- an explicit URL replaces an unrelated current page
- an already-open equivalent URL is not refreshed
- `llm_explore` performs entry navigation before the first Explore snapshot
- the navigation happens only once during a task
- a task such as `"https://ncesnext.com/"搜索大物` preserves the supplied URL

