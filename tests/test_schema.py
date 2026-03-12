"""Tests for schema name validation and related utilities."""
from __future__ import annotations

import pytest

from dbranch.schema import validate_name, full_schema_name, MYSQL_MAX_SCHEMA_LENGTH


class TestValidateName:
    """Tests for validate_name()."""

    def test_valid_simple_name(self):
        assert validate_name("myschema") is None

    def test_valid_underscore_start(self):
        assert validate_name("_private") is None

    def test_valid_alphanumeric(self):
        assert validate_name("app_v2_test") is None

    def test_reject_slash(self):
        err = validate_name("feature/branch")
        assert err is not None
        assert "/" in err

    def test_reject_space(self):
        err = validate_name("my schema")
        assert err is not None

    def test_reject_hyphen(self):
        err = validate_name("my-schema")
        assert err is not None

    def test_reject_leading_digit(self):
        err = validate_name("1schema")
        assert err is not None

    def test_reject_empty(self):
        err = validate_name("")
        assert err is not None

    def test_reject_special_chars(self):
        for char in ["@", "#", "$", "%", "!"]:
            err = validate_name(f"name{char}")
            assert err is not None, f"Expected rejection for char '{char}'"


class TestFullSchemaName:
    """Tests for full_schema_name()."""

    def test_default_prefix(self):
        assert full_schema_name("dbb_", "myschema") == "dbb_myschema"

    def test_custom_prefix(self):
        assert full_schema_name("test_", "foo") == "test_foo"

    def test_empty_prefix(self):
        assert full_schema_name("", "myschema") == "myschema"

    def test_exceeds_max_length(self):
        long_name = "a" * MYSQL_MAX_SCHEMA_LENGTH
        with pytest.raises(ValueError, match="exceeds"):
            full_schema_name("dbb_", long_name)

    def test_exactly_max_length(self):
        name = "a" * (MYSQL_MAX_SCHEMA_LENGTH - 4)
        result = full_schema_name("dbb_", name)
        assert len(result) == MYSQL_MAX_SCHEMA_LENGTH
