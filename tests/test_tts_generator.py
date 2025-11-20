
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to sys.path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tts_generator import TTSGenerator
from app.config import app_config

@pytest.fixture
def mock_config():
    # Mock the configuration to avoid needing a real API key
    with patch('app.tts_generator.app_config') as mock_cfg:
        mock_cfg.get.side_effect = lambda key, default=None: {
            "tts": {
                "api_key": "fake-key",
                "chunk_chars": 100
            }
        }.get(key, default)
        yield mock_cfg

def test_chunk_text_import_error(mock_config):
    """
    Test that instantiating TTSGenerator and calling _chunk_text
    fails if the import is incorrect (before fix) or succeeds (after fix).
    """
    # We need to mock OpenAI client because __init__ creates it
    with patch('app.tts_generator.OpenAI'):
        tts = TTSGenerator()

        text = "This is a test text that is long enough to be split." * 10

        # This call triggers the import inside _chunk_text
        try:
            chunks = tts._chunk_text(text)
            print(f"Successfully split text into {len(chunks)} chunks.")
        except ImportError as e:
            pytest.fail(f"ImportError during _chunk_text: {e}")
        except Exception as e:
             # If it's the specific ModuleNotFoundError we expect before fix
            if "No module named 'langchain.text_splitter'" in str(e):
                print("Caught expected ModuleNotFoundError for reproduction.")
                # Depending on whether we want this test to pass or fail before fix:
                # Usually for TDD I want it to fail.
                pytest.fail(f"Caught expected bug: {e}")
            else:
                raise e
