# Prompt templates for LLM-based healing

ANALYZE_ERROR_PROMPT = """
You are an expert Java/Build engineer.
Analyze the following build log failure and identify the root cause.

Scope of Analysis:
1. Source Code Errors (Java/internal logic)
2. Build Config Errors (Gradle/Maven plugins, dependencies)
3. Infrastructure/Environment Errors (Docker, Missing Tools, Network, JDK Version)

Build Log:
{build_log}

Instructions:
- If the error is about Docker (e.g., "client not initialized", "daemon not running"), identify it clearly.
- If a tool is missing or version is wrong (e.g., "wget failed", "gradle not found"), report it.
- Return strictly valid JSON.

Output Format (JSON):
{{
    "root_cause": "Detailed description of the error (e.g., 'Docker daemon not running' or 'Gradle 3.8.6 not found')",
    "file_path": "Path to the file needing fix, OR 'ENVIRONMENT' if it is a system issue",
    "confidence": "High/Medium/Low"
}}
"""

GENERATE_PATCH_PROMPT = """
You are an expert Java/Build engineer.
Based on the following error analysis, generate a Python script to fix the issue.
The script will be executed in the project root.
Use standard libraries (os, re, shutil) where possible.
If editing a file, read it, modify the content, and write it back.

Error Analysis:
{analysis}

Root Cause: {root_cause}
Target File: {file_path}

Constraints:
- Return ONLY the Python code block.
- Do not use markdown backticks.
- The code must be self-contained.

Python Fix Code:
"""
