import runpy

import pytest


def test_obsolete_mixed_bootstrap_is_hard_disabled():
    with pytest.raises(SystemExit, match="mixed-control bootstrap is disabled"):
        runpy.run_path("scripts/finish_e_stage_bootstrap.py", run_name="__main__")
