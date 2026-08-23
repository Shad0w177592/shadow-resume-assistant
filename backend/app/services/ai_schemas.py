JOB_PARSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["requirement_type", "summary", "source_text"],
                "properties": {
                    "requirement_type": {
                        "type": "string",
                        "enum": ["responsibility", "must_have", "nice_to_have", "education"],
                    },
                    "summary": {"type": "string"},
                    "source_text": {"type": "string"},
                },
            },
        }
    },
}

RESUME_REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["paragraphs"],
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["paragraph_id", "text", "reason"],
                "properties": {
                    "paragraph_id": {"type": "string"},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

EDIT_REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "reason"],
    "properties": {"text": {"type": "string"}, "reason": {"type": "string"}},
}


FABRICATED_EXPERIENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["heading", "meta", "text"],
    "properties": {
        "heading": {"type": "string"},
        "meta": {"type": "string"},
        "text": {"type": "string"},
    },
}
