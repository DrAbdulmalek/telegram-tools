# Contributing to Telegram Tools

Thank you for your interest in contributing! This guide will help you get started.

## Getting Started

### Prerequisites
- Python 3.10+
- Git
- A GitHub account
- A Telegram account (for live testing — optional for unit tests)

### Setup
```bash
git clone https://github.com/DrAbdulmalek/telegram-tools.git
cd telegram-tools
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -e .
pre-commit install
```

## How to Contribute

### Reporting Bugs
1. Check existing [Issues](https://github.com/DrAbdulmalek/telegram-tools/issues) first
2. Open a new issue using the **Bug Report** template
3. Include: OS, Python version, tool affected (`copy`/`forward`/`extract`/`process`), steps to reproduce

### Suggesting Features
1. Open an issue using the **Feature Request** template
2. Describe the use case and expected behavior
3. Include examples if possible

### Submitting Changes
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Run linting: `ruff check src/ app.py && flake8 src/ app.py`
5. Run tests: `pytest tests/ -v`
6. Run security scan: `bandit -r src/ -ll`
7. Commit with clear messages (see convention below)
8. Push to your fork and open a Pull Request

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `style:` Formatting, no code change
- `refactor:` Code restructuring
- `test:` Adding/updating tests
- `chore:` Maintenance tasks
- `security:` Security-related fix

Example: `feat(forwarder): add album grouping support`

## Code Style

- Follow PEP 8
- Line length: 100 characters (configurable in `pyproject.toml`)
- Use type hints everywhere
- Add docstrings to all public functions/classes
- Run `ruff check` and `flake8` before committing

## Testing

- All new features must include unit tests in `tests/`
- Tests run on Python 3.10, 3.11, and 3.12 in CI
- Live Telegram tests are skipped in CI — run them manually with credentials

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/telegram_tools --cov-report=html

# Run a specific test file
pytest tests/test_preprocess.py -v
```

## Pull Request Process

1. Ensure all CI checks pass (lint, test, security, docker)
2. Update documentation if needed
3. Keep PRs focused on a single concern
4. Respond to review feedback promptly
5. Do NOT commit session strings, API credentials, or `.session` files

## Questions?

Feel free to open a [Discussion](https://github.com/DrAbdulmalek/telegram-tools/discussions)
or reach out via [Issues](https://github.com/DrAbdulmalek/telegram-tools/issues).
