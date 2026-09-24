# AEGIS v2 Unified Runtime Commands

Use `main.py` as the single controller.

```powershell
python main.py run
python main.py readiness
python main.py verify
python main.py watch
python main.py profit
python main.py preflight
python main.py test
python main.py compile
python main.py clean
python main.py freeze
python main.py doctor
```

One-click Windows start:

```powershell
.\RUN_AEGIS.ps1
```

or double-click:

```text
RUN_AEGIS.bat
```

Docker now starts with:

```text
python main.py run
```

Backtest replay runtime:

```powershell
python main.py backtest-runtime path\to\replay.jsonl
```

The old main file is preserved as:

```text
main_legacy.py
```
