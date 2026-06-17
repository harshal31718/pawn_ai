import json
import re

def parse_action(output: str) -> dict:
    """
    Parses a JSON action from the LLM response, with fallback handling.
    Allows for nested JSON structures by finding the outermost matching braces.
    """
    first_brace = output.find('{')
    last_brace = output.rfind('}')
    
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate_json = output[first_brace:last_brace + 1]
        try:
            action = json.loads(candidate_json)
            if isinstance(action, dict) and "action" in action:
                return action
        except json.JSONDecodeError:
            # Fallback search scan for sub-strings
            for match in re.finditer(r'\{', output):
                start_idx = match.start()
                for end_idx in range(len(output), start_idx, -1):
                    try:
                        action = json.loads(output[start_idx:end_idx])
                        if isinstance(action, dict) and "action" in action:
                            return action
                    except json.JSONDecodeError:
                        continue
                        
    # Fallback: treat entire output as final answer
    return {"action": "final", "answer": output.strip()}
