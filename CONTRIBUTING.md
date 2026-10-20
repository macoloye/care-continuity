# Contributing

Start with a person's need and an example of the behavior you want to change. Code, accessibility feedback, translations, care scenarios, and knowledge reviews are all useful contributions.

## Development

Install with `python -m pip install -e .`, then run `python -m unittest discover -s tests -v`, `care-continuity`, and `care-continuity-sessions`. There are no runtime dependencies. CI runs the same checks on Python 3.11–3.14.

The HTTP tests bind an ephemeral loopback port; restricted sandboxes may need local networking permission. For UI changes, run `care-continuity-web` and follow [the browser walkthrough](docs/web.md). Keep browser rendering separate from permission rules, and test both the form contract and the underlying service behavior.

Keep permission rules in the services. Interfaces and model adapters should call them rather than duplicate them. Add a scenario when changing access, persistence, or lifecycle behavior. Use an injected clock for time-dependent tests. Comments should explain a boundary or a non-obvious choice; avoid narrating each line.

For a pull request, describe the need, resulting behavior, and relevant checks. Update the API documentation if a caller must do something differently. Database changes need a versioned migration and an upgrade test before release.

## Stories and knowledge

Use example records in issues, fixtures, and walkthroughs. Do not paste personal care stories, names, messages, or health records into public contributions. Removing a name alone is not enough to protect someone's privacy.

A knowledge proposal should identify its source, intended audience, setting, limitations, and publication rights. Experience must remain labelled as experience. Professional guidance requires an appropriately qualified reviewer; the current software does not support publishing it. Do not mark a fixture as real reviewed guidance.

Contributions are provided under the repository's MIT license. Third-party sources keep their own licenses; link and summarize only within the rights you have.
