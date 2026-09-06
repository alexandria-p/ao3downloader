# ao3_download_helper

The python project. `pyproject.toml` lives here, so this is where `uv` builds `.venv` and
where pytest finds its configuration.

| Path | What it is |
| --- | --- |
| `source_code/` | The application: console menu, downloader, parsers, and the local helper the web ui talks to. Imported as `source_code`. |
| `test/` | Its test suite. |
| `pyproject.toml`, `uv.lock` | The python project. |
| `ao3-env.ps1` | Shared launcher functions, used by `../run-locally.ps1` and `../../run_development_build.ps1`. They are also inlined into the bundle's `Start-Application.ps1`. |
| `build_artifacts.py` | Assembles the deployable bundle in `../../build`. |
| `test_build_artifacts.py` | Its tests, kept beside it rather than in `test/`. |

Runtime state - `settings.ini`, `data.json`, `logs/` and the downloads folder - lives one
level up in `powershell_source/`, not here. The launchers set their working directory
there while pointing `uv` at this folder.

## Running the tests

From this folder, so pytest picks up `[tool.pytest.ini_options]`:

```
uv run pytest
```

Running it from the repository root works too, but the settings there are ignored,
including the registration of the `ebook` marker.

## This file

It is also what `readme = "README.md"` in `pyproject.toml` points at, so hatchling refuses
to build the package without it. The description of the wider folder layout is in
`../README.md`.
