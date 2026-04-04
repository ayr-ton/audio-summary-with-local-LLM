"""Tests for the audio-summary CLI Ollama-dependent functions."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audio_summary.cli import summarize_text, research_text, ask_question_from_text


class TestSummarizeText:
    """Tests for the summarize_text function."""

    @pytest.fixture
    def mock_ollama_response(self):
        """Mock response from Ollama API."""
        return {"message": {"content": "# Summary\n\nThis is a test summary."}}

    def test_calls_ollama_with_correct_model(self, mocker):
        """Test that summarize_text calls Ollama with gpt-oss:20b."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Test Summary"}}

        summarize_text("Test content")

        mock_chat.assert_called_once()
        call_args = mock_chat.call_args[1]
        assert call_args["model"] == "gpt-oss:20b"

    def test_includes_system_prompt(self, mocker):
        """Test that system prompt is included in the call."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Test"}}

        summarize_text("Test content")

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        assert messages[0]["role"] == "system"
        assert "summarize" in messages[0]["content"].lower()

    def test_includes_text_in_user_prompt(self, mocker):
        """Test that the text is included in user prompt."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Test"}}

        test_text = "This is the text to summarize"
        summarize_text(test_text)

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        user_content = messages[1]["content"]
        assert test_text in user_content
        assert messages[1]["role"] == "user"

    def test_strips_thinking_chunks_from_result(self, mocker):
        """Test that thinking chunks are stripped from the result."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {
            "message": {
                "content": "# Summary\n\n<|thinking|>Thinking here<|/thinking|>\n\nActual content"
            }
        }

        result = summarize_text("Test")

        assert "<|thinking|>" not in result
        assert "<|/thinking|>" not in result
        assert "Thinking here" not in result
        assert "Actual content" in result

    def test_returns_content_from_response(self, mocker):
        """Test that function returns the message content."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {
            "message": {"content": "# Summary\n\nThis is the summary."}
        }

        result = summarize_text("Test")

        assert result == "# Summary\n\nThis is the summary."


class TestResearchText:
    """Tests for the research_text function."""

    def test_calls_ollama_with_correct_model(self, mocker):
        """Test that research_text calls Ollama with gpt-oss:20b."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Research Analysis"}}

        research_text("Test content")

        mock_chat.assert_called_once()
        call_args = mock_chat.call_args[1]
        assert call_args["model"] == "gpt-oss:20b"

    def test_includes_research_system_prompt(self, mocker):
        """Test that research system prompt is included."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Test"}}

        research_text("Test content")

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        assert messages[0]["role"] == "system"
        assert "research analyst" in messages[0]["content"].lower()

    def test_includes_research_sections_in_prompt(self, mocker):
        """Test that research sections are included in prompt."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "# Test"}}

        research_text("Test content")

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        user_content = messages[1]["content"]

        # Check for research sections
        assert "## Overview" in user_content
        assert "## Key Concepts" in user_content
        assert "## Detailed Analysis" in user_content
        assert "## Connections and Implications" in user_content
        assert "## Key Takeaways" in user_content

    def test_strips_thinking_chunks_from_result(self, mocker):
        """Test that thinking chunks are stripped from research result."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {
            "message": {
                "content": "# Research<|thinking|>Thinking<|/thinking|>\n\nContent"
            }
        }

        result = research_text("Test")

        assert "<|thinking|>" not in result
        assert "<|/thinking|>" not in result
        assert "Thinking" not in result
        assert "Content" in result


class TestAskQuestionFromText:
    """Tests for the ask_question_from_text function."""

    def test_calls_ollama_with_correct_model(self, mocker):
        """Test that ask_question_from_text calls Ollama with gpt-oss:20b."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "Answer"}}

        ask_question_from_text("Text content", "What is this?")

        mock_chat.assert_called_once()
        call_args = mock_chat.call_args[1]
        assert call_args["model"] == "gpt-oss:20b"

    def test_includes_question_context_prompt(self, mocker):
        """Test that question-answering system prompt is included."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "Answer"}}

        ask_question_from_text("Text", "Question")

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        assert messages[0]["role"] == "system"
        assert "question" in messages[0]["content"].lower()

    def test_includes_both_text_and_question_in_prompt(self, mocker):
        """Test that both text and question are included in user prompt."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {"message": {"content": "Answer"}}

        test_text = "This is the context"
        test_question = "What is the main point?"

        ask_question_from_text(test_text, test_question)

        call_args = mock_chat.call_args[1]
        messages = call_args["messages"]
        user_content = messages[1]["content"]

        assert test_text in user_content
        assert test_question in user_content
        assert "Question:" in user_content

    def test_strips_thinking_chunks_from_result(self, mocker):
        """Test that thinking chunks are stripped from answer."""
        mock_chat = mocker.patch("audio_summary.cli.ollama.chat")
        mock_chat.return_value = {
            "message": {"content": "Answer<|thinking|>Thinking<|/thinking|>"}
        }

        result = ask_question_from_text("Text", "Question")

        assert "<|thinking|>" not in result
        assert "<|/thinking|>" not in result
        assert "Thinking" not in result
        assert "Answer" in result
