from agent.services.cora_skills import CAPABILITIES

EXPECTED_CAPABILITY_NAMES = {
    "intent_router", "syllabus_analyzer", "calendar_extractor", "document_summarizer",
    "flashcard_generator", "quiz_generator", "study_planner", "mastery_analyzer",
    "course_qa", "general_assistant",
}


def test_registry_has_exactly_the_ten_expected_capabilities():
    assert set(CAPABILITIES.keys()) == EXPECTED_CAPABILITY_NAMES


def test_every_capability_has_trigger_notes_and_a_default_model():
    for name, skill in CAPABILITIES.items():
        assert skill.trigger_notes.strip(), f"{name} has empty trigger_notes"
        assert skill.default_model, f"{name} has no default_model"
        assert skill.implemented_by, f"{name} has no implemented_by"


def test_skill_name_matches_its_registry_key():
    # CAPABILITIES is keyed off each module's own SKILL.name — catches a
    # copy-pasted skill file whose internal name field wasn't updated.
    for key, skill in CAPABILITIES.items():
        assert skill.name == key


def test_calendar_extractor_declares_an_escalation_model():
    # This is the one capability with a documented Haiku->Sonnet escalation
    # path (agent/services/ask.py's ambiguous_context retry) — a missing
    # escalation_model here would mean the registry no longer reflects that.
    assert CAPABILITIES["calendar_extractor"].escalation_model is not None
