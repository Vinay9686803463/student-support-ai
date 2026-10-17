import os
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_get_knowledge_file_uses_b2_when_local_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app, "root_path", str(tmp_path))
    monkeypatch.setenv("B2_BUCKET_NAME", "test-bucket")

    response_body = BytesIO(b"%PDF-1.4 test content")
    fake_s3 = Mock()
    fake_s3.get_object.return_value = {"Body": response_body}

    with patch.object(app_module, "get_b2_client", return_value=fake_s3):
        result = app_module.get_knowledge_file(
            "knowledge_base/TEST/module1/test.pdf"
        )

    assert result.read() == b"%PDF-1.4 test content"
    fake_s3.get_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="knowledge_base/TEST/module1/test.pdf",
    )
    assert response_body.closed


def test_get_knowledge_file_rejects_path_traversal():
    with app_module.app.test_request_context("/"):
        with pytest.raises(Exception) as error:
            app_module.get_knowledge_file(
                "knowledge_base/../../outside.pdf"
            )
        assert getattr(error.value, "code", None) == 404
