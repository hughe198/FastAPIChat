import pytest
from pydantic import ValidationError

from ScrumpokerAPI.models import Vote, Settings, Reaction


def test_vote_requires_voter_and_vote():
    vote = Vote(voter="abc", vote="5")
    assert vote.voter == "abc"
    assert vote.vote == "5"


def test_vote_missing_field_raises():
    with pytest.raises(ValidationError):
        Vote(voter="abc")  # missing "vote"


def test_settings_defaults():
    settings = Settings(reveal=False, votingCard="Standard")
    assert settings.reactions == {}
    assert settings.missile_used_by == set()


def test_reaction_kind_defaults_to_normal():
    reaction = Reaction(id="1", emoji="🔥", from_voter="a", to_voter="b")
    assert reaction.kind == "normal"


def test_reaction_kind_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        Reaction(id="1", emoji="🔥", from_voter="a", to_voter="b", kind="not-a-real-kind")


def test_settings_mutable_defaults_are_not_shared_between_instances():
    """Pydantic gives each instance its own dict/set rather than a shared
    mutable default — this guards against a classic Python footgun where
    a `= {}` default accidentally gets shared across every instance."""
    s1 = Settings(reveal=False, votingCard="Standard")
    s2 = Settings(reveal=False, votingCard="Standard")

    s1.reactions["voter-1"] = []
    s1.missile_used_by.add("voter-1")

    assert s2.reactions == {}
    assert s2.missile_used_by == set()