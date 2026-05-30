# AGENTS.md

## Cursor Cloud specific instructions

### What this repository is

Michael Liao’s **Python 3 tutorial** companion repo: standalone lesson scripts under `samples/` and a small WSGI **learning assistant** in `teach/learning.py` that executes code submitted from the online course (liaoxuefeng.com). There is no monorepo, no root `requirements.txt`, and no unified test or lint CI.

### Runtime requirements

- **Python 3.4+** (stdlib only for `teach/` and most `samples/`). The VM image typically ships with Python 3.12.
- No mandatory `pip install` at the repository root. Individual lessons may document extra packages (Flask, Pillow, `mysql-connector-python`, `aiohttp`, etc.) under `samples/`.

### Primary service (tutorial code runner)

| Item | Value |
|------|--------|
| Entry | `teach/learning.py` |
| Bind | `127.0.0.1:39093` |
| Expected log | `Ready for Python code on port 39093...` |

Start in a persistent session (recommended: tmux), from `teach/`:

```bash
python3 learning.py
```

**POST `/run`** (used by the external tutorial site) requires:

- `Host: local.liaoxuefeng.com:39093`
- `Origin` containing `.liaoxuefeng.com`
- `Content-Type: application/x-www-form-urlencoded` with a `code` field

**GET `/`** serves a local HTML form for manual testing without the external site.

For browser E2E against the real course UI, map `local.liaoxuefeng.com` to `127.0.0.1` in `/etc/hosts`.

### Running lesson samples

```bash
python3 samples/basic/hello.py
```

Other samples are independent; some need optional local services (MySQL on 3306, Flask on 5000, etc.) as noted in each script.

### Lint / test (no project harness)

There is no `pytest`, `ruff`, or pre-commit configuration in this repo. Reasonable local checks:

```bash
python3 -m compileall -q teach samples/basic
python3 samples/basic/hello.py
```

Smoke-test the learning assistant while it is running:

```bash
curl -s http://127.0.0.1:39093/
curl -s -X POST http://127.0.0.1:39093/run \
  -H 'Host: local.liaoxuefeng.com:39093' \
  -H 'Origin: https://www.liaoxuefeng.com' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'code=print(42)'
```

### Optional services (only when exercising matching lessons)

| Service | Port | Start |
|---------|------|--------|
| `samples/web/do_wsgi.py` | 8000 | `python3 samples/web/do_wsgi.py` |
| Flask samples | 5000 | `python3 samples/web/do_flask.py` (etc.) |
| `teach/learning.py` | 39093 | see above |
| MySQL (DB samples) | 3306 | external; see `samples/db/do_mysql.py` |

Do not add Docker, database, or dev-server startup to the VM **update script**; start them per task in tmux when needed.
