"""Private native-process environment/output guards; never launches Blender."""

from pathlib import Path

import pytest
from run_native_preview_workflows import outside_workspace, private_environment


def test_private_environment_replaces_all_user_and_temp_overrides(tmp_path):
    profile = tmp_path / "private-profile"
    inherited = {"BLENDER_USER_EXTENSIONS": "C:/old-profile", "blender_user_config": "C:/old-config",
                 "BLENDER_USER_RESOURCES": "C:/old-resources", "TEMP": "C:/shared-temp",
                 "TMP": "C:/shared-temp", "TMPDIR": "C:/shared-temp", "PATH": "preserved"}
    env = private_environment(profile, inherited)
    assert env["PATH"] == "preserved"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "BLENDER_USER_EXTENSIONS" not in env and "blender_user_config" not in env
    for key in ("BLENDER_USER_RESOURCES", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
                "BLENDER_USER_DATAFILES", "TEMP", "TMP", "TMPDIR"):
        assert Path(env[key]).is_relative_to(profile)
        assert Path(env[key]).is_dir()
    assert inherited["TEMP"] == "C:/shared-temp"  # parent environment untouched


def test_relative_output_is_refused_before_resolve():
    with pytest.raises(ValueError, match="absolute"):
        outside_workspace(Path("relative-evidence"), {})


def test_onedrive_company_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="OneDrive"):
        outside_workspace(tmp_path / "OneDrive - Company" / "evidence", {})


def test_configured_onedrive_root_is_refused_even_without_onedrive_name(tmp_path):
    root = tmp_path / "Synced Documents"
    with pytest.raises(ValueError, match="configured OneDrive"):
        outside_workspace(root / "evidence", {"OneDriveCommercial": str(root)})


def test_worktree_output_is_refused(tmp_path):
    worktree = tmp_path / "feature-worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: unrelated", encoding="utf-8")
    with pytest.raises(ValueError, match="worktrees"):
        outside_workspace(worktree / "evidence", {})
