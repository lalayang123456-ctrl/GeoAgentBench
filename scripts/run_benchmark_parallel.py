import os
import sys
import json
import time
import concurrent.futures
from datetime import datetime
from pathlib import Path

# Add project root to path to allow imports
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from examples.vln_agent import VLNAgent, AgentConfig

import threading

# Load environment variables from .env file
load_dotenv(project_root / ".env")

# Configuration
AGENTS = [
    # "gemini-2.5-pro-thinking",
    "gemini-3-pro-preview"
    # "gpt-5.2",
    # "claude-opus-4-6-thinking"
]
TASKS_DIR = project_root / "tasks"
LOGS_DIR = project_root / "logs"

# Global state for progress tracking
print_lock = threading.Lock()
progress_lock = threading.Lock()
completed_count = 0
total_tasks_count = 0

def get_tasks():
    """Get all vis and nav tasks from tasks_test."""
    # We include both 'vis_' (Visual) and 'nav_' (Navigation) tasks
    tasks = []
    tasks.extend(list(TASKS_DIR.glob("vis_*.json")))
    tasks.extend(list(TASKS_DIR.glob("nav_*.json")))
    tasks.extend(list(TASKS_DIR.glob("height_*.json")))
    tasks.extend(list(TASKS_DIR.glob("dis_*.json")))
    tasks.extend(list(TASKS_DIR.glob("angle_*.json")))
    
    tasks = sorted(tasks)
    
    if not tasks:
        with print_lock:
            print("No tasks found in tasks_test!")
        return []
    
    # Return task IDs
    return [t.stem for t in tasks]

def get_agent_config(agent_name: str) -> AgentConfig:
    """Get agent-specific configuration from config/agent_configs.json.
    
    Falls back to default environment variables if agent not found in config file.
    """
    config = AgentConfig.from_env()  # Use defaults as fallback
    
    # Load agent configs from JSON file
    agent_configs_path = project_root / "config" / "agent_configs.json"
    try:
        if agent_configs_path.exists():
            with open(agent_configs_path, 'r', encoding='utf-8') as f:
                agent_configs = json.load(f)
            if agent_name in agent_configs:
                agent_cfg = agent_configs[agent_name]
                config.api_base_url = agent_cfg.get("api_base_url", config.api_base_url)
                config.api_key = agent_cfg.get("api_key", config.api_key)
    except (json.JSONDecodeError, IOError) as e:
        with print_lock:
            print(f"Warning: Failed to load agent_configs.json: {e}")
    
    config.model_name = agent_name
    return config

def run_single_task(agent_name: str, task_id: str):
    """Run a single task with specific agent."""
    with print_lock:
        print(f"[{agent_name}] Starting task: {task_id}")
    
    # Configure agent with per-agent settings
    config = get_agent_config(agent_name)
    # Ensure URL is correct - assuming default localhost:8000
    if not config.benchmark_url:
        config.benchmark_url = "http://localhost:8000"
        
    try:
        agent = VLNAgent(config)
        
        # Run task
        # We use a unique agent_id for the session
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        agent_run_id = f"{agent_name}_{timestamp}"
        
        # Get task details checks for max_steps (Local File Read)
        task_max_steps = 30
        try:
            task_file_path = TASKS_DIR / f"{task_id}.json"
            if task_file_path.exists():
                with open(task_file_path, 'r', encoding='utf-8') as f:
                    task_data = json.load(f)
                    
                    # Calculate max_steps from visual_path length if available
                    visual_path = task_data.get("visual_path", [])
                    if visual_path and len(visual_path) > 0:
                        # Use length of visual_path (number of nodes) * 1.5
                        # If user meant "steps" (intervals), it would be len-1, but len is safer.
                        task_max_steps = int(round(len(visual_path) * 1.5))
                        # Ensure a reasonable minimum? e.g. at least 10? 
                        # User didn't ask, but let's stick to their formula.
                        # with print_lock:
                        #    print(f"[{agent_name}] Calculated max_steps: {task_max_steps} (path len: {len(visual_path)})")
                    elif task_data.get("max_steps"):
                        task_max_steps = task_data.get("max_steps")
        except Exception as e:
            with print_lock:
                print(f"[{agent_name}] Failed to read task file, using default max_steps=30: {e}")

        result = agent.run(
            task_id=task_id,
            max_steps=task_max_steps,
            agent_id=agent_run_id
        )
        
        # Check if session creation failed (no trajectory in result)
        if "trajectory" not in result:
            error_msg = result.get("error", "Unknown error - no trajectory returned")
            with print_lock:
                print(f"[{agent_name}] Session creation failed for {task_id}: {error_msg}")
            return False
        
        # Save log
        log_filename = f"{agent_name}_{task_id}_{timestamp}.jsonl"
        log_path = LOGS_DIR / log_filename
        
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(log_path, 'w', encoding='utf-8') as f:
            # 1. Write session_start event
            # We need to extract initial state from the first step of trajectory if available, 
            # or reconstruct it. The best way is to look at the first step's state or the result.
            # Assuming the task started, we can infer some info.
            
            # Since we don't return initial_state explicitly in result, we use the first step's state
            # but that's after the first move logic? No, trajectory[0] is step 0 or 1?
            # vln_agent.py records step 1 after decide_action.
            # Actually, the user wants "session_start" as the first line.
            
            initial_state = {}
            if result["trajectory"]:
                 # Just use the first recorded state as initial for now, or empty.
                 # Ideally vln_agent should return initial_observation separately.
                 # For now, we'll try to use the first state found.
                 first_state = result["trajectory"][0].get("state", {})
                 initial_state = first_state
            
            session_start_event = {
                "event": "session_start",
                "session_id": result.get("session_id", agent_run_id),
                "agent_id": agent_name,
                "task_id": task_id,
                "mode": "agent", # or auto
                "timestamp": timestamp, # Start timestamp
                "initial_state": initial_state,
                "task_description": "" # We might need to fetch this from task file or agent result if added
            }
            # Try to get task description from task file again if possible
            try:
                task_file_path = TASKS_DIR / f"{task_id}.json"
                if task_file_path.exists():
                    with open(task_file_path, 'r', encoding='utf-8') as tf:
                        td = json.load(tf)
                        session_start_event["task_description"] = td.get("description", "")
            except:
                pass
                
            f.write(json.dumps(session_start_event, ensure_ascii=False) + "\n")
            
            # 2. Write action events from trajectory
            for step_data in result["trajectory"]:
                raw_action = step_data.get("action", {})
                # Create a copy for the 'action' field without promoted fields to avoid duplication
                # User requested to keep the "latter" reason (top-level)
                action_clean = raw_action.copy()
                reason = action_clean.pop("reason", None)
                duration = action_clean.pop("agent_vlm_duration_seconds", None)
                # Remove other potentially redundant fields if needed, but these are the main ones
                
                action_event = {
                    "event": "action",
                    "session_id": result.get("session_id", agent_run_id),
                    "timestamp": step_data.get("timestamp", ""),
                    "step": step_data.get("step"),
                    "state": step_data.get("state"),
                    "action": action_clean, # Cleaner action object
                    "available_moves": step_data.get("available_moves"),
                    "image_path": step_data.get("image_path", ""),
                    "agent_type": "agent",
                    "agent_vlm_duration_seconds": duration,
                    "reason": reason,
                    "raw_response": action_clean.get("raw_response")
                }
                
                # Check for suspicious reasons and print raw response
                if not reason or "Failed to parse" in str(reason):
                    with print_lock:
                         # Try to find raw response either in the top level (if added) or in action_clean
                         raw_resp = action_clean.get("raw_response", "N/A")
                         print(f"[{agent_name}] [Task {task_id}] [Step {step_data.get('step')}] WARN: Reason='{reason}'. RAW RESPONSE: {repr(raw_resp)}")
                # Clean up action object if needed (remove duplicates if we promoted fields)
                # The user want raw action object or specific fields? 
                # User asked: agent_vlm_duration_seconds and reason.
                # vln_agent.py puts them inside 'action'. 
                # The target format has them at top level or inside action?
                # Target example: 
                # "action": {"type": "move", "move_id": 1}, ... but user text says:
                # "同时agent_vlm_duration_seconds和reason这两个字段也不要忘记"
                # Looking at user target file content (view_file output Step 9):
                # Line 2: "action": {"type": "move", "move_id": 1}, ...
                # It does NOT show agent_vlm_duration_seconds in top level.
                # But the user REQUESTED: "agent_vlm_duration_seconds and reason... don't forget".
                # I will add them to the top level of the event to be safe, or ensure they are in action.
                # In the target file provided, I don't see them. 
                # But the user *asked* for them. So I will add them at the top level of the action event.
                
                f.write(json.dumps(action_event, ensure_ascii=False) + "\n")
            
        global completed_count
        with progress_lock:
            completed_count += 1
            current_progress = completed_count
            
        with print_lock:
             print(f"[{current_progress}/{total_tasks_count}] [{agent_name}] Finished {task_id}. Log: {log_filename}")
        return True
        
    except Exception as e:
        with print_lock:
            print(f"[{agent_name}] Error running {task_id}: {e}")
        return False

def main():
    global total_tasks_count, LOGS_DIR
    
    # Create timestamped log directory for this run
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOGS_DIR = project_root / "logs" / f"log_{current_time}"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Starting Parallel Benchmark Runner...")
    print(f"Agents: {AGENTS}")
    print(f"Logs will be saved to: {LOGS_DIR}")
    
    tasks = get_tasks()
    print(f"Tasks ({len(tasks)}): {tasks}")
    
    if not tasks:
        return
    
    # Create work items
    work_items = []
    for agent in AGENTS:
        for task in tasks:
            work_items.append((agent, task))
            
    total_tasks_count = len(work_items)
    print(f"Total runs: {total_tasks_count}")
    
    # Run in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=120) as executor:
        futures = {
            executor.submit(run_single_task, agent, task): (agent, task) 
            for agent, task in work_items
        }
        
        for future in concurrent.futures.as_completed(futures):
            # Results are printed inside the task now
            pass
                
    print("\nAll tasks completed.")

if __name__ == "__main__":
    main()
