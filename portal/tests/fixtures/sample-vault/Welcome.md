---
tags:
  - intro
---

# Welcome

This fixture vault exercises the Obsidian syntax that the Quartz build must
render. It deliberately has **no** `index.md`, so the portal's fallback index
generator should kick in.

Links: [[Projects/Alpha]] and a [[Second Note]] with an [[Second Note|alias]].

Highlights: ==this text is highlighted==.

A hidden comment follows and must not appear in output: %%secret editor note%%

> [!note] Callout check
> Callouts should render with Obsidian semantics.
> > [!warning]- Nested collapsible
> > Collapsed by default.

- [ ] open task
- [x] done task
- [?] custom task character
