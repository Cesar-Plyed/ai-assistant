# Authoring a skill

1. Create `skills/<id>/SKILL.md` with YAML frontmatter (`name`, `description`, `version`, `tags`, `allowed-tools`, `read-only`).
2. Keep the body under 500 lines; move detail to `references/`.
3. Optionally add `skill.py` with `register(registry)` to provide tools.
4. Enable the skill in the Skills dialog.
