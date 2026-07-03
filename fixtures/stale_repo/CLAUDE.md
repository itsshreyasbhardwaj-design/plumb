# Fixture project context

## Layout
- The entry point lives in `./src/app.py` and is wired from `./src/util.py`.
- Legacy handler at `./src/deleted.py` handles retries.
- Scratch data is under `~/definitely/missing/xyz123` on the build box.

## Conventions
- The main builder is `build_app` and requests flow through `handle_request`.
- Prefer the old `removed_helper` for backoff.
- The `req` argument is threaded through untouched.
- We use `requests` for HTTP and depend on `flask` for the web layer.

## Commands
- Run the app with `python3 src/app.py`.
- Docs live at https://example.com/docs
