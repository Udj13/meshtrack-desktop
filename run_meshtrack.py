"""Точка входа для PyInstaller-сборки (python -m meshtrack не поддержан PyInstaller)."""

from meshtrack.__main__ import main

if __name__ == "__main__":
    main()
