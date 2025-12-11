# Install build tool into system python3
python3 -m pip install build

# Build wheel (run in repo root)
python3 -m build

# Validate in a clean venv using python3/pip3
python3 -m venv .venv_test_utfw
.\.venv_test_utfw\Scripts\Activate.ps1
pip3 install .\dist\utfw-3.0.0-py3-none-any.whl
python3 -c "import UTFW, sys; print('UTFW OK', getattr(UTFW,'__version__','no __version__'), 'at', UTFW.__file__)"