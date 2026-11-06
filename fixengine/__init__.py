"""Auto-fix engine: router, quotas, budget guard, sandbox, validator and orchestrator.

Golden rule: only router.py chooses models, and every model call goes through
guard.py and is written to the ledger (store.py). Nothing else may call a model.
"""

from .envfile import load_env_file as _load_env_file  # noqa: E402

_load_env_file()      # reads .env if it exists; real environment variables always win
