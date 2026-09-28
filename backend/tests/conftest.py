import os
import sys
import tempfile
from pathlib import Path

# isolate every test run: temp data dir, no real AI calls
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="leadchecker-test-")
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.samples import water_treatment  # noqa: E402


@pytest.fixture
def faulty():
    return water_treatment(errors=True)


@pytest.fixture
def clean():
    return water_treatment(errors=False)


def by_tag(doc, tag):
    return [e for e in doc["entities"] if e.get("tag") == tag]
