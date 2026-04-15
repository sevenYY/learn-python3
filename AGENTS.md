# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is a Python 3 tutorial / sample code repository (~112 standalone scripts). There is no formal build system, `requirements.txt`, or CI pipeline. Each `.py` file under `samples/` is an independent example run directly with `python3`.

### Running samples

```
python3 samples/basic/hello.py
python3 samples/db/do_sqlite.py
```

### Running tests

Unit tests and doctests use the stdlib `unittest` / `doctest` modules:

```
python3 -m unittest samples/test/dict_unittest.py -v
python3 samples/test/dict_doctest.py -v
```

### Services

- **Learning helper** (`teach/learning.py`): WSGI server on port 39093. Start with `python3 teach/learning.py`. Test with curl using `Host: local.liaoxuefeng.com:39093` and `Origin: http://www.liaoxuefeng.com` headers.
- **Flask sample** (`samples/web/do_flask.py`): Dev server on port 5000. Start with `python3 samples/web/do_flask.py`.

### Known caveats

- Some `samples/async/` scripts use `@asyncio.coroutine` and `asyncio.get_event_loop()` patterns removed/deprecated in Python 3.10+. These will fail on Python 3.12. This is expected — the repo targets Python 3.4+ originally.
- `samples/db/do_mysql.py` and `samples/db/do_sqlalchemy.py` (with MySQL) require a running MySQL server and `mysql-connector-python` pip package; skip these if MySQL is unavailable.
- `samples/gui/hello_gui.py` requires a display server (tkinter); it will not work in headless environments.
- `samples/mail/` scripts require live SMTP/POP3 credentials — skip in CI/cloud.
- Third-party pip packages needed by specific samples: `flask`, `aiohttp`, `Pillow`, `sqlalchemy`. These are installed by the update script.
