# Install build tool into system python
python -m pip install build

# Build wheel (run in repo root)
python -m build

# Validate in a clean venv
python -m venv .venv_test_utfw
.\.venv_test_utfw\Scripts\Activate.ps1
pip install .\dist\utfw-4.0.0-py3-none-any.whl
python -c "import UTFW, sys; print('UTFW OK', getattr(UTFW,'__version__','no __version__'), 'at', UTFW.__file__)"