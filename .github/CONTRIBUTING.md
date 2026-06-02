# Contributing

Thanks for your interest! This is a **portfolio project** showcasing backend engineering depth in AI agent systems — feel free to explore, fork, and learn from the code.

## Ways to Contribute

- **Bug fixes**: Found something broken? PRs welcome!
- **Documentation**: Typos, unclear explanations, missing context — all worth fixing.
- **New features**: Open an issue first to discuss before implementing.

## Development Setup

See [README.md](README.md#quick-start) for the full setup guide.

## Code Style

- Python: Follow PEP 8. Use type hints where practical.
- Comments: English docstrings for functions, Chinese inline comments for business logic (consistent with existing code).
- Commit messages: Conventional Commits format preferred (`feat:`, `fix:`, `docs:`, `refactor:`).

## Pull Request Checklist

- [ ] Code is documented (docstrings + inline comments where non-obvious)
- [ ] Existing E2E tests pass (`rasa test e2e --e2e-tests e2e_tests/`)
- [ ] No commented-out code or debug prints left behind
- [ ] `.env.example` updated if new config keys are added
