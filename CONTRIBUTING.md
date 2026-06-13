# Contributing to Steam Market Tracker

Thank you for your interest in contributing to the Steam Market Tracker! We welcome bug reports, feature suggestions, documentation updates, and code contributions to make this tool better for everyone.

Please take a moment to review this guide to ensure a smooth contribution process.

---

## Code of Conduct

By participating in this project, you agree to maintain a respectful and welcoming environment for all contributors. Please be polite, constructive, and collaborative.

---

## How Can I Contribute?

### 1. Reporting Bugs
If you find a bug:
- Check the existing Github Issues to see if it has already been reported.
- If not, open a new issue.
- Describe the bug clearly, include steps to reproduce, and specify your operating system.
- Provide any error logs printed in the console (with sensitive information like webhook URLs or file paths removed).

### 2. Suggesting Enhancements
We welcome ideas for new features (e.g., adding interactive graphs, supporting new alerts, etc.):
- Open an issue explaining your proposed feature, why it is useful, and how you imagine it working.
- Wait for feedback from maintainers before writing code to make sure it aligns with the project goals.

### 3. Submitting Code Changes
If you'd like to fix a bug or add a feature:
1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Tbh-monitor.git
   cd Tbh-monitor
   ```
3. Set up the development environment (see below).
4. Create a new branch for your work:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b bugfix/your-bugfix-name
   ```
5. Make your code changes.
6. Run local tests and linters to verify your changes.
7. Commit and push your changes to your fork.
8. Open a **Pull Request** against our `main` (or `master`) branch.

---

## Local Development Setup

To run and test changes locally:

1. **Set Up a Virtual Environment**:
   ```bash
   python -m venv .venv
   # Activate on Windows:
   .venv\Scripts\activate
   # Activate on macOS/Linux:
   source .venv/bin/activate
   ```
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   # Install development packages (optional):
   pip install flake8
   ```
3. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and set up your paths (your local `.env` is git-ignored and safe).
4. **Run the Application**:
   ```bash
   python main.py
   ```

---

## Style & Standards

To keep the codebase clean and maintainable:
- **Python Code Style**: Follow standard PEP 8 coding guidelines.
- **Linter Verification**: Before submitting a PR, verify that your code passes flake8 checking:
  ```bash
  flake8 src/ tests/
  ```
  *(We ignore line length warnings up to 120 characters, but keep code neat and remove unused imports).*
- **Comments & Type Hints**: Add descriptive docstrings and type hints (`typing`) to new helper functions or modules.

---

## Running Tests

We write unit tests to keep background workers, data mappings, database actions, and notification systems stable.

Before opening a pull request, run all unit tests to verify everything passes:
```bash
python -m unittest discover tests/
```

If you add a new feature or helper method, please add matching tests in the `tests/` folder.

---

## Pull Request Checklist

When submitting a pull request, please ensure:
- [ ] Your code works correctly and starts up without error.
- [ ] Code follows Python conventions and passes `flake8` checks.
- [ ] Existing tests pass and new features have test coverage where applicable.
- [ ] PR descriptions clearly describe the problem solved or the feature added.

Thank you again for contributing!
