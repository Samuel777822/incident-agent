import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).parent / ".env")

MODEL = "openai/gpt-oss-120b"

PROMPT_TEMPLATE = """You are a careful automated software engineer fixing one production incident.

Given the incident details and repository files below, generate the minimal, precise find-and-replace edit to fix the bug.

CRITICAL RULES:
1. Touch EXACTLY ONE source code file.
2. NEVER modify test files (e.g. test_*.py, *_test.py), configuration files (.env, pyproject.toml, etc.), or dependencies.
3. The "old_text" must be an EXACT snippet copied directly from the target file, including all whitespace and indentation.
4. Choose "old_text" with enough surrounding context so that it appears EXACTLY ONCE in the file.
5. The "new_text" must be the minimal modification that fixes the root cause.
6. Return ONLY a single valid JSON object, with no markdown code fences and no commentary before or after.

JSON format:
{{
  "file_path": "relative/path/to/file.py",
  "old_text": "exact snippet to replace",
  "new_text": "replacement snippet",
  "explanation": "brief explanation of fix"
}}

=== INCIDENT MESSAGE ===
{message}

=== TRACEBACK ===
{traceback}

=== ROOT CAUSE & RECOMMENDED FIX ===
Root cause: {root_cause}
Recommended fix: {recommended_fix}

=== REPOSITORY FILES ===
{files_text}
"""


def call_patch_model(client, prompt):
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    return client.chat.completions.create(**kwargs)


def parse_patch_json(text):
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    raw = json.loads(text[start : end + 1])
    file_path = str(raw.get("file_path", "")).strip().replace("\\", "/")
    old_text = raw.get("old_text")
    new_text = raw.get("new_text")
    explanation = str(raw.get("explanation", "")).strip()

    if not file_path or old_text is None or new_text is None:
        raise ValueError("Missing required patch fields: file_path, old_text, or new_text")

    return {
        "file_path": file_path,
        "old_text": old_text,
        "new_text": new_text,
        "explanation": explanation,
    }


def validate_patch(repo_folder, patch):
    file_path = patch["file_path"]
    rel_path = Path(file_path)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return False, f"Invalid file path: {file_path}"

    target_file = (Path(repo_folder) / rel_path).resolve()
    repo_root = Path(repo_folder).resolve()

    try:
        target_file.relative_to(repo_root)
    except ValueError:
        return False, f"File path escapes repository: {file_path}"

    if not target_file.is_file():
        return False, f"Target file does not exist: {file_path}"

    # Do not allow modifying test files or secret/config files
    name_lower = target_file.name.lower()
    if "test" in name_lower or name_lower.startswith(".env") or name_lower.endswith((".db", ".sqlite")):
        return False, f"Refusing to patch protected or test file: {file_path}"

    content = target_file.read_text(encoding="utf-8")
    count = content.count(patch["old_text"])
    if count == 0:
        return False, f"old_text was not found in {file_path}"
    if count > 1:
        return False, f"old_text occurs {count} times in {file_path}; must occur exactly once"

    return True, "Patch is valid"


def apply_patch(repo_folder, patch):
    target_file = Path(repo_folder) / patch["file_path"]
    content = target_file.read_text(encoding="utf-8")
    if patch["old_text"] not in content:
        raise ValueError(f"old_text not found in {patch['file_path']}")
    
    new_content = content.replace(patch["old_text"], patch["new_text"], 1)
    target_file.write_text(new_content, encoding="utf-8")
    return new_content


def generate_patch(repo_folder, incident_message, traceback, root_cause, recommended_fix, files_text):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not found in .env")

    client = Groq(api_key=api_key)
    prompt = PROMPT_TEMPLATE.format(
        message=incident_message or "N/A",
        traceback=traceback or "N/A",
        root_cause=root_cause or "N/A",
        recommended_fix=recommended_fix or "N/A",
        files_text=files_text or "",
    )

    last_error = "unknown error"
    for _ in range(2):
        response = call_patch_model(client, prompt)
        choice = response.choices[0]
        try:
            patch = parse_patch_json(choice.message.content or "")
            valid, msg = validate_patch(repo_folder, patch)
            if not valid:
                last_error = f"Patch validation failed: {msg}"
                continue
            return patch
        except Exception as err:
            last_error = f"Model output parse failed: {err}"
            continue

    raise RuntimeError(f"Could not generate a valid patch: {last_error}")
