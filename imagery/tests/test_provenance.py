from __future__ import annotations

from foundinspace.textures.provenance import producer_identity


def test_producer_identity_includes_code_and_git_state() -> None:
    identity = producer_identity()

    assert len(identity["code_tree_sha256"]) == 64
    assert identity["package_version"] == "0.1.0"
    assert len(identity["git_sha"]) == 40
    assert isinstance(identity["git_dirty"], bool)
