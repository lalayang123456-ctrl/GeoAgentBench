"""
VLN Agent Template - Universal Agent for VLN Benchmark

This template supports any OpenAI-compatible API (OpenAI, yunwu.ai, Claude, etc.)
with continuous dialogue and image understanding capabilities.

Requirements:
    pip install openai requests python-dotenv

Usage:
    1. Set your API key in environment variable or .env file
    2. Start the VLN Benchmark server: python main.py
    3. Run this script: python vln_agent.py

Configuration:
    - API_BASE_URL: API endpoint (e.g., https://yunwu.ai/v1)
    - API_KEY: Your API key
    - MODEL_NAME: Model to use (e.g., gpt-4o, claude-3-opus)
"""

import os
import base64
import json
import time
from datetime import datetime
import concurrent.futures
# import requests  # Removed requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

# Local imports for direct execution
from engine.session_manager import session_manager
from engine.action_executor import action_executor
from engine.logger import session_logger
from engine.observation_generator import get_observation_generator
# We need to replicate _build_observation logic or import it. 
# Importing from api.routes is risky due to router setup. 
# Let's import necessary dependencies to build observation locally.
from engine.direction_calculator import direction_calculator
from engine.metadata_cache import metadata_cache
from engine.geofence_checker import geofence_checker
from api.models import AvailableMove # To match structure if needed, or just use dicts

# Load environment variables from .env file
# Search order: VLN_BENCHMARK/.env -> project root/.env
_current_dir = Path(__file__).parent.parent  # VLN_BENCHMARK directory
_env_file = _current_dir / ".env"
if not _env_file.exists():
    _env_file = _current_dir.parent / ".env"  # Project root
load_dotenv(_env_file)

# Debug: Print which .env file was loaded
# print(f"[Config] Loading .env from: {_env_file}")


@dataclass
class AgentConfig:
    """Configuration for the VLN Agent."""
    
    # API Configuration
    api_base_url: str = "https://yunwu.ai/v1"
    api_key: str = ""
    model_name: str = "gpt-4o"
    
    # Benchmark Configuration
    benchmark_url: str = "http://localhost:8000"
    
    # Agent Behavior
    max_history_turns: int = 1000  # Number of conversation turns to keep
    temperature: float = 0.3
    max_tokens: int = 16384
    
    # Retry Configuration
    max_retries: int = 3
    retry_delay: float = 2.0
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables."""
        return cls(
            api_base_url=os.getenv("API_BASE_URL", "https://yunwu.ai/v1"),
            api_key=os.getenv("API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "gpt-4o"),
            benchmark_url=os.getenv("BENCHMARK_URL", "http://localhost:8000"),
            max_history_turns=int(os.getenv("MAX_HISTORY_TURNS", "1000")),
            temperature=float(os.getenv("TEMPERATURE", "0.3")),
        )


class VLNAgent:
    """
    Universal VLN Agent with continuous dialogue support.
    
    Supports any OpenAI-compatible API including:
    - OpenAI (gpt-4o, gpt-4-turbo)
    - yunwu.ai (aggregated API)
    - Claude (via compatible endpoint)
    - Local models (Ollama, vLLM)
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize the agent.
        
        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or AgentConfig.from_env()
        
        if not self.config.api_key:
            raise ValueError("API_KEY is required. Set it in environment or config.")
        
        # Initialize OpenAI client with custom base URL
        self.client = OpenAI(
            base_url=self.config.api_base_url,
            api_key=self.config.api_key
        )
        
        # Session state
        self.session_id: Optional[str] = None
        self.messages: List[Dict[str, Any]] = []
        self.step_count: int = 0
        
        # System prompt for VLN task
        self.system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self, task_id: Optional[str] = None) -> str:
        """Build the system prompt for the VLN agent by loading from external file.
        
        Args:
            task_id: Optional task ID to determine which prompt file to load.
                     - height_* tasks -> system_prompt_height.txt
                     - dis_* tasks -> system_prompt_dis.txt
                     - angle_* tasks -> system_prompt_angle.txt
                     - vis_* or nav_* tasks -> system_prompt_nav.txt
                     - others -> system_prompt.txt (default)
        """
        # Determine prompt filename based on task_id prefix
        prompt_filename = "system_prompt.txt"  # default
        if task_id:
            if task_id.startswith("height_"):
                prompt_filename = "system_prompt_height.txt"
            elif task_id.startswith("dis_"):
                prompt_filename = "system_prompt_dis.txt"
            elif task_id.startswith("angle_"):
                prompt_filename = "system_prompt_angle.txt"
            elif task_id.startswith("vis_") or task_id.startswith("nav_"):
                prompt_filename = "system_prompt_nav.txt"
        
        # Try to load from external file
        system_prompt_path = Path(__file__).parent.parent / "config" / prompt_filename
        
        if system_prompt_path.exists():
            try:
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    # print(f"[System Prompt] Loaded from: {system_prompt_path}")
                    # print(f"[System Prompt] Length: {len(content)} characters")
                    # print(f"[System Prompt] Preview: {content[:200]}...")
                    return content
            except Exception as e:
                pass # print(f"[Warning] Failed to load system prompt from file: {e}")
        
        # Fallback to default prompt
        return """You are a navigation agent exploring Street View environments. Your goal is to follow the task instructions and navigate to the correct destination.

## Action Format
Respond with a JSON object containing:
```json
{
  "thought": "Your reasoning about what you see and what to do next",
  "action": "move" | "rotation" | "stop",
  "move_id": <integer, required if action is "move">,
  "heading": <0-360, required if action is "rotation">,
  "answer": "<your answer, required if action is stop>"
}
```

IMPORTANT: Respond ONLY with valid JSON, no additional text."""
    
    # Helper for local observation building
    def _local_get_available_moves(self, session) -> list:
        current_pano_id = session.state.pano_id
        
        metadata = metadata_cache.get(current_pano_id)
        if not metadata:
            return []
        
        links = metadata.get('links', [])
        if not links:
            return []
            
        links = geofence_checker.filter_links(session.geofence, links)
        
        current_location = (session.state.lat, session.state.lng)
        if current_location[0] is None:
            current_location = metadata_cache.get_location(current_pano_id)
            
        link_pano_ids = [l.get('panoId') or l.get('pano_id') for l in links]
        locations = metadata_cache.get_all_locations(link_pano_ids)
        
        moves = direction_calculator.calculate_available_moves(
            links, session.state.heading, current_location, locations
        )
        moves = direction_calculator.sort_moves_by_direction(moves)
        
        return [{"id": m["id"], "direction": m["direction"], "distance": m.get("distance"), "heading": m.get("heading")} for m in moves]

    def _local_build_observation(self, session) -> dict:
        available_moves = self._local_get_available_moves(session)
        
        image_url = None
        panorama_url = None
        center_heading = 0.0
        
        if session.step_count >= 0:
             image_url = f"/temp_images/{session.session_id}/step_{session.step_count}.jpg"
             
             pano_id = session.state.pano_id
             metadata = metadata_cache.get(pano_id)
             if metadata:
                 center_heading = metadata.get('center_heading', 0.0) or 0.0
                 
        return {
            "task_description": session.task_config.get('description', ''),
            "current_image": image_url,
            "panorama_url": panorama_url,
            "heading": session.state.heading if session.state else 0.0,
            "pitch": session.state.pitch if session.state else 0.0,
            "fov": session.state.fov if session.state else 90.0,
            "center_heading": center_heading,
            "available_moves": available_moves,
            # Validation Context
            "pano_id": session.state.pano_id,
            "lat": session.state.lat,
            "lng": session.state.lng,
            "capture_date": getattr(session.state, 'capture_date', None) or (metadata.get('capture_date') if metadata else None)
        }

    def create_session(self, task_id: str, agent_id: str = "vln_agent") -> dict:
        """Create a new evaluation session (Local Call)."""
        session = session_manager.create_session(
            agent_id=agent_id,
            task_id=task_id,
            mode="agent"
        )
        
        if session is None:
            raise ValueError(f"Task not found: {task_id}")
            
        self.session_id = session.session_id
        
        # Rebuild system prompt based on task type
        self.system_prompt = self._build_system_prompt(task_id)
        
        # Log session start
        # session_logger.log_session_start(session)
        
        # Generate initial view (Local)
        try:
            generator = get_observation_generator()
            generator.generate_observation(
                pano_id=session.state.pano_id,
                heading=session.state.heading,
                pitch=session.state.pitch,
                fov=session.state.fov,
                session_id=session.session_id,
                step=session.step_count
            )
        except Exception as e:
            pass # print(f"Error generating initial observation: {e}")
            
        # Reset conversation history with task-specific system prompt
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.step_count = 0
        
        return self._local_build_observation(session)
    
    def execute_action(self, action: dict) -> dict:
        """Execute an action (Local Call)."""
        result = action_executor.execute(self.session_id, action)
        
        # Log action
        if result.success:
            session = session_manager.get_session(self.session_id)
            available_moves = self._local_get_available_moves(session)
            # session_logger.log_action(session, action, result.to_dict(), available_moves)
            
            # Match validation context injection
            if result.observation:
                result.observation["pano_id"] = session.state.pano_id
                result.observation["lat"] = session.state.lat
                result.observation["lng"] = session.state.lng
                result.observation["capture_date"] = getattr(session.state, 'capture_date', None)

                # Try to get capture_date from metadata if missing in state
                if not result.observation["capture_date"]:
                     metadata = metadata_cache.get(session.state.pano_id)
                     if metadata:
                         result.observation["capture_date"] = metadata.get('capture_date')

            if result.done:
                pass # session_logger.log_session_end(session)
                
        # Return dict matching API response structure
        return {
            "success": result.success,
            "observation": result.observation, # This is already a dict from action_executor
            "done": result.done,
            "done_reason": result.done_reason,
            "error": result.error
        }
    
    def get_image_base64(self, image_url: str) -> Optional[str]:
        """Download image and convert to base64."""
        if not image_url:
            return None
            
        try:
            full_url = f"{self.config.benchmark_url}{image_url}"
            response = requests.get(full_url, timeout=10)
            response.raise_for_status()
            return base64.b64encode(response.content).decode("utf-8")
        except Exception as e:
            # print(f"Failed to download image: {e}")
            return None
    
    @staticmethod
    def _format_heading_compass(heading: float) -> str:
        """
        Format heading as compass-style bearing.
        
        Args:
            heading: Heading in degrees (0-360)
            
        Returns:
            Formatted string like "249°W" or "0°N"
        """
        heading = heading % 360
        
        # Determine cardinal/intercardinal direction
        directions = [
            (0, "N"),      # North
            (45, "NE"),    # Northeast
            (90, "E"),     # East
            (135, "SE"),   # Southeast
            (180, "S"),    # South
            (225, "SW"),   # Southwest
            (270, "W"),    # West
            (315, "NW"),   # Northwest
            (360, "N")     # North again
        ]
        
        # Find the closest direction
        for i in range(len(directions) - 1):
            deg1, dir1 = directions[i]
            deg2, dir2 = directions[i + 1]
            
            if deg1 <= heading < deg2:
                # Determine which direction is closer
                if abs(heading - deg1) <= abs(heading - deg2):
                    return f"{heading:.0f}°{dir1}"
                else:
                    return f"{heading:.0f}°{dir2}"
        
        # Default to North
        return f"{heading:.0f}°N"
    
    @staticmethod
    def _format_pitch(pitch: float) -> str:
        """
        Format pitch with UP/DOWN indicator.
        
        Args:
            pitch: Pitch in degrees (-85 to 85)
            
        Returns:
            Formatted string like "30°UP", "20°DOWN", or "0°"
        """
        if pitch > 0:
            return f"{pitch:.0f}°UP"
        elif pitch < 0:
            return f"{abs(pitch):.0f}°DOWN"
        else:
            return "0°"
    
    def _build_user_message(self, observation: dict) -> Dict[str, Any]:
        """Build a user message from the observation."""
        task_description = observation["task_description"]
        available_moves = observation["available_moves"]
        
        # Get current orientation
        heading = observation.get("heading", 0)
        pitch = observation.get("pitch", 0)
        fov = observation.get("fov", 90)
        
        # Build moves description
        moves_text = "\n".join([
            f"  {m['id']}: {m['direction']}" + (f" ({m['distance']:.1f}m)" if m.get('distance') else "")
            for m in available_moves
        ])
        
        # Build rotation options (relative to current heading)
        def normalize_heading(h):
            return h % 360
        
        rotation_options = f"""  - Look LEFT: heading={normalize_heading(heading - 90)}
  - Look RIGHT: heading={normalize_heading(heading + 90)}
  - Look BACK: heading={normalize_heading(heading + 180)}
  - Look UP: pitch=30 (keep current heading={heading})
  - Look DOWN: pitch=-30 (keep current heading={heading})
  - Or any custom heading (0-360) and pitch (-85 to 85)"""
        
        # Build text content
        heading_compass = self._format_heading_compass(heading)
        pitch_formatted = self._format_pitch(pitch)
        text_content = f"""**Step {self.step_count + 1}**

**Task:** {task_description}

**Current View:**
- Heading: {heading_compass}
- Pitch: {pitch_formatted}

**Available Moves:**
{moves_text}

🔄 **ROTATE** - Look in a different direction (without moving):
{rotation_options}

Analyze the image and decide your next action."""
        
        # Build message content
        content = [{"type": "text", "text": text_content}]
        
        # Add image if available
        image_url = observation.get("panorama_url") or observation.get("current_image")
        if image_url:
            image_base64 = self.get_image_base64(image_url)
            if image_base64:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                        "detail": "high"
                    }
                })
        
        return {"role": "user", "content": content}
    
    def _parse_response(self, response_text: str, observation: dict) -> dict:
        """Parse the model's response into an action."""
        try:
            # Clean up markdown code blocks
            json_str = response_text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                parts = json_str.split("```")
                # Find the part that looks like JSON
                for part in parts:
                    if "{" in part and "}" in part:
                        json_str = part
                        break
            
            # Remove any non-json text before/after braces
            # Find the LAST '}' which is definitely the end of the main JSON object
            end_idx = json_str.rfind('}')
            if end_idx == -1:
                 raise ValueError("No JSON object found (missing closing brace)")
            
            # Iterate through all '{' positions to find the valid start
            # This handles cases where text contains braces (e.g. LaTeX \frac{a}{b})
            valid_json = None
            current_idx = 0
            while True:
                start_idx = json_str.find('{', current_idx)
                if start_idx == -1 or start_idx > end_idx:
                    break
                
                candidate = json_str[start_idx : end_idx + 1]
                try:
                    decision = json.loads(candidate)
                    valid_json = decision
                    break # Found valid JSON!
                except json.JSONDecodeError:
                    # Move past this '{' and try the next one
                    current_idx = start_idx + 1
            
            if valid_json is None:
                 raise ValueError("Could not find valid JSON object in response")
            
            decision = valid_json
            
            # Support both uppercase and lowercase keys provided by different prompts
            thought = decision.get("THOUGHT") or decision.get("thought", "")
            action_str = decision.get("ACTION") or decision.get("action", "")
            
            # Parse the function-call style action string: e.g., "MOVE(1)", "ROTATION(45, 0)", "STOP(ARRIVED)"
            import re
            match = re.match(r"([A-Z]+)\((.*)\)", action_str.strip())
            
            if not match:
                # Fallback or error if format doesn't match
                # Try to parse legacy format if it's just "move"
                if action_str.lower() == "move":
                     return {"type": "move", "move_id": int(decision.get("move_id", 1)), "reason": thought}
                # Fallback: stay in place with current orientation
                current_heading = observation.get("heading", 0)
                current_pitch = observation.get("pitch", 0)
                return {"type": "rotation", "heading": current_heading, "pitch": current_pitch, "reason": f"Invalid action format: {action_str}"}
            
            command = match.group(1).upper()
            args_str = match.group(2)
            
            if command == "MOVE":
                move_id = int(args_str.strip())
                return {
                    "type": "move", 
                    "move_id": move_id,
                    "reason": thought
                }
                
            elif command == "ROTATION":
                # Expecting "yaw, pitch" or just "yaw"
                args = [float(x.strip()) for x in args_str.split(',')]
                yaw = args[0]
                pitch = args[1] if len(args) > 1 else 0.0
                
                return {
                    "type": "rotation",
                    "heading": yaw,  # New format calls it yaw/heading, mapping to absolute heading
                    "pitch": pitch,
                    "reason": thought
                }
                
            elif command == "STOP":
                # Clean up quotes if present in args_str
                answer = args_str.strip().strip("'").strip('"')
                return {
                    "type": "stop", 
                    "answer": answer,
                    "reason": thought
                }
                
            else:
                # Fallback: stay in place with current orientation
                current_heading = observation.get("heading", 0)
                current_pitch = observation.get("pitch", 0)
                return {"type": "rotation", "heading": current_heading, "pitch": current_pitch, "reason": f"Unknown command: {command}"}
                
        except Exception as e:
            print(f"[{self.config.model_name}] Failed to parse response: {e}")
            print(f"[{self.config.model_name}] Response was: {repr(response_text)[:500]}...")
            
            # Attempt to repair JSON using GPT-4o-mini
            print(f"[{self.config.model_name}] Attempting to repair JSON with GPT-4o-mini...")
            repaired_json = self._repair_json_with_gpt4o(response_text)
            
            if repaired_json:
                try:
                    # Try parsing the repaired JSON
                    return self._parse_repaired_json(repaired_json)
                except Exception as repair_e:
                    print(f"[{self.config.model_name}] Repair also failed: {repair_e}")
            
            # Fallback: stay in place with current orientation
            current_heading = observation.get("heading", 0)
            current_pitch = observation.get("pitch", 0)
            return {
                "type": "rotation", 
                "heading": current_heading,
                "pitch": current_pitch,
                "reason": "Failed to parse response, using fallback.",
                "raw_response": response_text
            }
    
    def _repair_json_with_gpt4o(self, malformed_response: str) -> Optional[str]:
        """
        Use GPT-4o-mini to repair a malformed JSON response.
        
        Args:
            malformed_response: The original malformed response text
            
        Returns:
            Repaired JSON string, or None if repair failed
        """
        repair_prompt = """You are a JSON repair assistant. The following text is a malformed JSON response from an AI agent. 
Your task is to fix the JSON formatting issues and return ONLY the corrected JSON.

Common issues to fix:
1. Missing quotes around string values in ACTION field (e.g., ACTION: MOVE(1) should be "ACTION": "MOVE(1)")
2. Incorrect punctuation or missing commas
3. Unquoted keys
4. Trailing commas

The expected format is:
```json
{
  "THOUGHT": "<reasoning text>",
  "ACTION": "MOVE(number)" | "ROTATION(heading, pitch)" | "STOP(content)"
}
```

IMPORTANT: 
- The ACTION value must be a quoted string like "MOVE(1)", "ROTATION(160, 0)", "STOP(27.8)", or "STOP(arrived)"
- Return ONLY the corrected JSON, no explanations

Malformed response to fix:
"""
        
        try:
            # Create a separate client for GPT-4o-mini repair
            repair_client = OpenAI(
                base_url=self.config.api_base_url,
                api_key=self.config.api_key
            )
            
            response = repair_client.chat.completions.create(
                model="gpt-4o-mini",  # Changed from gpt-4o to gpt-4o-mini for cost efficiency
                messages=[
                    {"role": "system", "content": repair_prompt},
                    {"role": "user", "content": malformed_response[:2000]}  # Truncate to avoid token limits
                ],
                max_tokens=500,
                temperature=0.0
            )
            
            repaired = response.choices[0].message.content.strip()
            print(f"[GPT-4o-mini Repair] Repaired response: {repaired[:200]}...")
            return repaired
            
        except Exception as e:
            print(f"[GPT-4o-mini Repair] Failed to call repair API: {e}")
            return None
    
    def _parse_repaired_json(self, repaired_text: str) -> dict:
        """
        Parse the repaired JSON response.
        
        Args:
            repaired_text: The repaired JSON text from GPT-4o
            
        Returns:
            Action dict
        """
        import re
        
        # Clean up markdown code blocks
        json_str = repaired_text
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            parts = json_str.split("```")
            if len(parts) >= 2:
                json_str = parts[1]
        
        json_str = json_str.strip()
        decision = json.loads(json_str)
        
        thought = decision.get("THOUGHT") or decision.get("thought", "")
        action_str = decision.get("ACTION") or decision.get("action", "")
        
        match = re.match(r"([A-Z]+)\((.*)\)", action_str.strip())
        
        if not match:
            raise ValueError(f"Invalid action format after repair: {action_str}")
        
        command = match.group(1).upper()
        args_str = match.group(2)
        
        if command == "MOVE":
            move_id = int(args_str.strip())
            return {
                "type": "move", 
                "move_id": move_id,
                "reason": f"[Repaired] {thought}"
            }
        elif command == "ROTATION":
            args = [float(x.strip()) for x in args_str.split(',')]
            yaw = args[0]
            pitch = args[1] if len(args) > 1 else 0.0
            return {
                "type": "rotation",
                "heading": yaw,
                "pitch": pitch,
                "reason": f"[Repaired] {thought}"
            }
        elif command == "STOP":
            answer = args_str.strip().strip("'").strip('"')
            return {
                "type": "stop", 
                "answer": answer,
                "reason": f"[Repaired] {thought}"
            }
        else:
            raise ValueError(f"Unknown command after repair: {command}")
    
    def _trim_history(self):
        """Trim conversation history to keep only recent turns."""
        max_messages = 1 + (self.config.max_history_turns * 2)  # system + turns
        if len(self.messages) > max_messages:
            # Keep system message and last N turns
            self.messages = [self.messages[0]] + self.messages[-(self.config.max_history_turns * 2):]
    
    def decide_action(self, observation: dict) -> dict:
        """
        Use the LLM to decide the next action based on the observation.
        
        This method maintains conversation history for context.
        """
        # Build and add user message
        user_message = self._build_user_message(observation)
        self.messages.append(user_message)
        
        # Trim history if too long
        self._trim_history()
        
        # Call API with retry
        step_start_time = time.time()
        
        for attempt in range(self.config.max_retries):
            try:
                vlm_start_time = time.time()
                response = self.client.chat.completions.create(
                    model=self.config.model_name,
                    messages=self.messages,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature
                )
                vlm_duration = time.time() - vlm_start_time
                
                raw_content = response.choices[0].message.content
                # Handle case where API returns dict directly instead of string
                if isinstance(raw_content, dict):
                    assistant_message = json.dumps(raw_content)
                else:
                    assistant_message = raw_content.strip() if raw_content else ""
                # print(f"\n[{self.config.model_name}] Response:\n{assistant_message}\n")
                
                # Debug logging for empty responses
                if not assistant_message:
                    print(f"[{self.config.model_name}] Warning: Empty response received.")
                    print(f"[{self.config.model_name}] Full Response Object: {response}")
                    try:
                        print(f"[{self.config.model_name}] Finish Reason: {response.choices[0].finish_reason}")
                    except:
                        pass
                
                # Add assistant response to history
                self.messages.append({"role": "assistant", "content": assistant_message})
                
                # Parse and return action
                action = self._parse_response(assistant_message, observation)
                
                # Add timing info
                action["agent_vlm_duration_seconds"] = round(vlm_duration, 3)
                action["agent_total_duration_seconds"] = round(time.time() - step_start_time, 3)
                
                # Always store raw response for debugging
                action["raw_response"] = assistant_message
                
                return action
                
            except Exception as e:
                error_str = str(e)
                print(f"API call failed (attempt {attempt + 1}/{self.config.max_retries}): {error_str}")
                
                # Check for rate limit
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = self.config.retry_delay * (2 ** attempt)
                    print(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                elif attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)
                else:
                    break
        
        # Fallback action: stay in place with current orientation
        print("All retries failed. Using fallback action (rotation in place).")
        current_heading = observation.get("heading", 0)
        current_pitch = observation.get("pitch", 0)
        return {
            "type": "rotation", 
            "heading": current_heading, 
            "pitch": current_pitch,
            "reason": "All API retries failed, using fallback."
        }
    
    def run(self, task_id: str, max_steps: int = 25, agent_id: str = "vln_agent") -> dict:
        """
        Run the agent on a task.
        
        Args:
            task_id: The task to run
            max_steps: Maximum number of steps before stopping
            agent_id: Identifier for this agent run
            
        Returns:
            Result dict with success status, trajectory, and statistics
        """
        # print(f"\n{'='*60}")
        # print(f"VLN Agent Starting")
        # print(f"  Model: {self.config.model_name}")
        # print(f"  API: {self.config.api_base_url}")
        # print(f"  Task: {task_id}")
        # print(f"{'='*60}\n")
        
        # Create session
        try:
            observation = self.create_session(task_id, agent_id)
        except Exception as e: # requests.exceptions.HTTPError removed
            # print(f"Failed to create session: {e}")
            return {"success": False, "error": str(e)}
        
        # print(f"Task Description: {observation['task_description']}")
        # print(f"Session ID: {self.session_id}\n")
        
        trajectory = []
        
        while self.step_count < max_steps:
            # print(f"\n{'─'*40}")
            # print(f"Step {self.step_count + 1}")
            # print(f"{'─'*40}")
            
            # Show available moves
            # print("Available moves:")
            # for m in observation["available_moves"]:
            #     dist = f" ({m['distance']:.1f}m)" if m.get('distance') else ""
            #     print(f"  [{m['id']}] {m['direction']}{dist}")
            
            # Get agent's decision
            action = self.decide_action(observation)
            # print(f"Action: {action}")
            
            # Record trajectory
            current_timestamp = datetime.now().isoformat()
            trajectory.append({
                "step": self.step_count + 1,
                "timestamp": current_timestamp,
                "action": action,
                "state": {
                    "pano_id": observation.get("pano_id"),
                    "heading": observation.get("heading"),
                    "pitch": observation.get("pitch"),
                    "fov": observation.get("fov"),
                    "lat": observation.get("lat"),
                    "lng": observation.get("lng"),
                    "capture_date": observation.get("capture_date")
                },
                "available_moves": observation["available_moves"],
                "image_path": observation.get("current_image", "").lstrip("/") # Remove leading slash
            })
            
            # Execute action
            result = self.execute_action(action)
            
            if result["done"]:
                # print(f"\n{'='*60}")
                # print(f"Task Completed!")
                # print(f"  Reason: {result['done_reason']}")
                # print(f"  Total Steps: {self.step_count + 1}")
                # print(f"{'='*60}\n")
                
                return {
                    "success": True,
                    "done_reason": result["done_reason"],
                    "total_steps": self.step_count + 1,
                    "trajectory": trajectory,
                    "session_id": self.session_id,
                    "timestamp": current_timestamp # Last step timestamp
                }
            
            observation = result["observation"]
            self.step_count += 1
        
        # print(f"\nMax steps ({max_steps}) reached!")
        return {
            "success": False,
            "done_reason": "max_steps",
            "total_steps": self.step_count,
            "trajectory": trajectory,
            "session_id": self.session_id
        }


def main():
    """Example usage with yunwu.ai API."""
    
    # Option 1: Load from environment variables
    # Set these in your .env file:
    #   API_BASE_URL=https://yunwu.ai/v1
    #   API_KEY=sk-xxxxx
    #   MODEL_NAME=gpt-4o
    
    # Option 2: Load from environment (reads .env file)
    config = AgentConfig.from_env()
    
    # Create agent
    agent = VLNAgent(config)
    
    # Run on a task
    result = agent.run(
        task_id="visual_nav_mcdonalds_20260123_004758_2",
        max_steps=30,
        agent_id="vln_agent_demo"
    )
    
    # Print summary
    print("\n" + "="*60)
    print("RESULT SUMMARY")
    print("="*60)
    print(f"Success: {result['success']}")
    print(f"Reason: {result.get('done_reason')}")
    print(f"Total Steps: {result.get('total_steps')}")
    print(f"Session ID: {result.get('session_id')}")


if __name__ == "__main__":
    main()
