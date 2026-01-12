import os
import json
import re
from src.utils.logger import logger
from src.healing.prompts import ANALYZE_ERROR_PROMPT, GENERATE_PATCH_PROMPT

try:
    import openai
except ImportError:
    openai = None

class LLMHealer:
    def __init__(self, project_root):
        self.project_root = project_root
        self.config = self._load_config()
        self.api_key = self.config.get("api_key") or os.getenv("LLM_API_KEY")
        self.model = self.config.get("model", "gpt-3.5-turbo")
        self.provider = self.config.get("provider", "openai")
        self.base_url = self.config.get("base_url", "http://localhost:11434")
        self.is_gemini = "gemini" in self.model.lower() and self.provider != "ollama"
        self.is_ollama = self.provider == "ollama"
        
        if not self.is_ollama and (not self.api_key or self.api_key == "YOUR_OPENAI_API_KEY_HERE"):
            logger.warning("Valid LLM API Key not found in llm_config.json or environment. LLMHealer will not function.")
        else:
            if not self.is_gemini and not self.is_ollama:
                if openai:
                    openai.api_key = self.api_key
                else:
                    logger.warning("openai module not installed. LLMHealer will not function for OpenAI models.")

    def _load_config(self):
        """
        Loads configuration from llm_config.json in the project root.
        """
        agent_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        config_path = os.path.join(agent_root, "llm_config.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load llm_config.json: {e}")
        return {}

    def heal(self, logs: str) -> bool:
        """
        Attempts to fix the build error using LLM.
        Returns True if a fix was applied, False otherwise.
        """
        # Validator: Check for API key (skip for ollama)
        if not self.is_ollama and (not self.api_key or self.api_key == "YOUR_OPENAI_API_KEY_HERE"):
            logger.warning("Skipping LLM healing: API key invalid.")
            return False
            
        # Validator: Check for module dependency if not Gemini/Ollama
        if not self.is_gemini and not self.is_ollama and not openai:
            logger.warning("Skipping LLM healing: openai module missing for OpenAI model.")
            return False
            
        logger.info(f"Engaging LLMHealer (Provider: {self.provider}, Model: {self.model})...")
        try:
            # Step 1: Analyze Error
            analysis = self._analyze_error(logs)
            if not analysis:
                logger.warning("LLM failed to analyze error.")
                return False
                
            logger.info(f"LLM Analysis: {json.dumps(analysis, indent=2)}")
            
            # Step 2: Generate Fix
            fix_code = self._generate_fix(analysis)
            if not fix_code:
                logger.warning("LLM failed to generate fix.")
                return False
                
            logger.info("LLM generated fix code. Applying...")
            
            # Step 3: Apply Fix
            success = self._apply_fix(fix_code)
            return success
            
        except Exception as e:
            logger.error(f"LLMHealer process failed: {e}")
            return False

    def _query_llm(self, prompt: str) -> str:
        """
        Queries the LLM. Automatically switches between OpenAI, Gemini, and Ollama.
        """
        if self.is_ollama:
            return self._query_ollama(prompt)
            
        if self.is_gemini:
            return self._query_google_rest(prompt)
            
        # Default: OpenAI
        if not openai:
            raise ImportError("openai module not installed")
        
        try:
            # Simple standard OpenAI call
            response = openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful expert software engineer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return None

    def _query_ollama(self, prompt: str) -> str:
        """
        Uses Ollama API.
        """
        import urllib.request
        import json
        
        url = f"{self.base_url}/api/chat"
        headers = {'Content-Type': 'application/json'}
        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": "You are a helpful expert software engineer. Output strictly in JSON format.\n" + prompt}
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.0
            }
        }
        
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('message', {}).get('content')
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
            return None

    def _query_google_rest(self, prompt: str) -> str:
        """
        Uses Google Gemini REST API via standard urllib to avoid extra dependencies.
        Now supports exponential backoff for 429 Rate Limit errors.
        """
        import urllib.request
        import urllib.error
        import json
        import time
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{
                "parts": [{"text": "You are a helpful expert software engineer.\n" + prompt}]
            }]
        }
        
        retries = 5
        delay = 5
        
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    try:
                        return result['candidates'][0]['content']['parts'][0]['text']
                    except (KeyError, IndexError):
                        logger.error(f"Unexpected Gemini response format: {result}")
                        return None
                        
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt < retries:
                        logger.warning(f"Gemini API Rate Limited (429). Retrying in {delay} seconds... (Attempt {attempt+1}/{retries})")
                        time.sleep(delay)
                        delay *= 2
                        continue
                    else:
                        logger.error("Gemini API Rate Limit exceeded after maximum retries.")
                else:
                    logger.error(f"Gemini API call failed: {e.code} - {e.reason}")
                return None
            except Exception as e:
                logger.error(f"Gemini API call failed: {e}")
                return None
        return None

    def _extract_relevant_logs(self, logs: str, max_lines=100) -> str:
        """
        Extracts relevant lines from build logs to feed to LLM.
        Prioritizes 'Caused by', 'FAILURE:', 'Error:', and stack traces.
        """
        lines = logs.split('\n')
        relevant_lines = []
        
        # Keywords to look for
        keywords = ["Caused by:", "FAILURE:", "Error:", "Exception", "Build failed", "What went wrong:"]
        
        # Scan for interesting lines
        hit_indices = [i for i, line in enumerate(lines) if any(k in line for k in keywords)]
        
        if not hit_indices:
            # Fallback to tail if no keywords found
            return "\n".join(lines[-100:])
            
        # Collect context around hits
        kept_indices = set()
        for i in hit_indices:
            start = max(0, i - 10) # 10 lines before
            end = min(len(lines), i + 20) # 20 lines after
            kept_indices.update(range(start, end))
            
        sorted_indices = sorted(list(kept_indices))
        
        # Reconstruct log
        snippet = []
        last_idx = -1
        for idx in sorted_indices:
            if last_idx != -1 and idx > last_idx + 1:
                snippet.append("... (skipped) ...")
            snippet.append(lines[idx])
            last_idx = idx
            
        return "\n".join(snippet)

    def _analyze_error(self, logs: str) -> dict:
        """
        Queries LLM to analyze the build log.
        """
        # Use smart log extraction
        log_snippet = self._extract_relevant_logs(logs)
        
        prompt = ANALYZE_ERROR_PROMPT.format(build_log=log_snippet)
        
        content = self._query_llm(prompt)
        logger.info(f"Raw LLM Response: {content}")
        
        if not content:
            return None

        try:
            # Parse JSON from content
            # Try to find JSON block first
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            return json.loads(content)
        except Exception as e:
            logger.error(f"Error parsing analysis JSON: {e}")
            return None

    def _generate_fix(self, analysis: dict) -> str:
        """
        Queries LLM to generate python patch script.
        """
        prompt = GENERATE_PATCH_PROMPT.format(
            analysis=json.dumps(analysis),
            root_cause=analysis.get("root_cause", "Unknown"),
            file_path=analysis.get("file_path", "Unknown")
        )
        
        content = self._query_llm(prompt)
        if not content:
            return None
            
        # Extract code block
        code_match = re.search(r"```python(.*?)```", content, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        else:
            return content.replace("```", "").strip()
            
    def _apply_fix(self, code: str) -> bool:
        """
        Executes the generated python code.
        """
        try:
            # Change safe execution scope?
            # We run it in the project root context
            current_cwd = os.getcwd()
            os.chdir(self.project_root)
            
            logger.info("Executing patch script...")
            # Use exec safely? We are an agent, we assume trust for now or sandbox.
            # For this MVP, exec is fine.
            exec(code, {'os': os, 're': re, 'print': print})
            
            os.chdir(current_cwd)
            return True
        except Exception as e:
            logger.error(f"Failed to apply patch: {e}")
            return False
