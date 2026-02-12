"""
Unified Evaluation for All Task Types (nav, vis, height, dis, angle)

Usage:
    python scripts/evaluate_all.py --dir logs/log_20260128_xxx
    python scripts/evaluate_all.py --dir logs/log_20260128_xxx --tasks-dir tasks_perception
"""

import argparse
import sys
import json
import re
import math
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.metadata_cache import metadata_cache

# Default task directory
TASKS_DIR = Path(__file__).parent.parent / "tasks"

# Thresholds
NAV_SUCCESS_THRESHOLD_M = 15.0  # meters
HEIGHT_TOLERANCE_PCT = 0.15     # ±10%
DISTANCE_TOLERANCE_PCT = 0.2   # ±15%
ANGLE_TOLERANCE_DEG = 30.0      # ±30 degrees


def detect_task_type(task_id: str) -> str:
    """Detect task type from task_id prefix."""
    if task_id.startswith("nav_"):
        return "nav"
    elif task_id.startswith("vis_"):
        return "vis"
    elif task_id.startswith("height_"):
        return "height"
    elif task_id.startswith("dis_"):
        return "dis"
    elif task_id.startswith("angle_"):
        return "angle"
    return "unknown"


def load_task_config(task_id: str, custom_tasks_dir: Path = None) -> Optional[Dict]:
    """Load task config from file, searching custom dir first, then default TASKS_DIR."""
    search_paths = []
    
    if custom_tasks_dir:
        search_paths.append(custom_tasks_dir)
    
    search_paths.append(TASKS_DIR)
    
    for dir_path in search_paths:
        p = dir_path / f"{task_id}.json"
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
    
    return None


def extract_number(answer_str) -> Optional[float]:
    """Extract the first number from an answer string."""
    if answer_str is None:
        return None
    
    if isinstance(answer_str, (int, float)):
        return float(answer_str)
    
    answer_str = str(answer_str).strip()
    if not answer_str:
        return None
    
    # Try direct parse
    try:
        return float(answer_str)
    except ValueError:
        pass
    
    # Regex for numbers
    pattern = r'[-+]?\d*\.?\d+'
    matches = re.findall(pattern, answer_str)
    
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            pass
    
    return None


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def get_distance(pano1: str, pano2: str, local_cache: Dict = None) -> float:
    """Get distance between two panorama IDs."""
    if pano1 == pano2:
        return 0.0
    
    loc1 = local_cache.get(pano1) if local_cache else None
    loc2 = local_cache.get(pano2) if local_cache else None
    
    if not loc1:
        loc1 = metadata_cache.get_location(pano1)
    if not loc2:
        loc2 = metadata_cache.get_location(pano2)
        
    if not loc1 or not loc2:
        return float('inf')
    return haversine(loc1[0], loc1[1], loc2[0], loc2[1])


def calculate_angular_error(pred: float, truth: float) -> float:
    """Calculate smallest difference between two angles (0-360)."""
    diff = abs(pred - truth) % 360
    return min(diff, 360 - diff)


def reconstruct_path_from_events(events: List[Dict], start_pano: str = None) -> List[str]:
    """Reconstruct path from log events."""
    path = []
    if start_pano:
        path.append(start_pano)
    
    for e in events:
        if e.get("event") == "session_start":
            state = e.get("initial_state", {})
            if state.get("pano_id"):
                if not path or path[-1] != state["pano_id"]:
                    path.append(state["pano_id"])
        elif e.get("event") == "action":
            state = e.get("state", {})
            if state.get("pano_id"):
                if not path or path[-1] != state["pano_id"]:
                    path.append(state["pano_id"])
    
    return path


def calculate_trajectory_length(events: List[Dict]) -> float:
    """Calculate trajectory length from events."""
    points = []
    
    for e in events:
        if e.get("event") == "session_start":
            state = e.get("initial_state", {})
            if "lat" in state and "lng" in state:
                points.append((state["lat"], state["lng"]))
        elif e.get("event") == "action":
            state = e.get("state", {})
            if "lat" in state and "lng" in state:
                pt = (state["lat"], state["lng"])
                if not points or points[-1] != pt:
                    points.append(pt)
    
    total_len = 0.0
    for i in range(len(points) - 1):
        total_len += haversine(points[i][0], points[i][1], points[i+1][0], points[i+1][1])
    
    return total_len


def count_steps(events: List[Dict]) -> int:
    """Count action steps from events."""
    return sum(1 for e in events if e.get("event") == "action")


def get_stop_answer(events: List[Dict]) -> Optional[str]:
    """Extract answer from stop action."""
    for e in reversed(events):
        if e.get("event") == "action":
            action = e.get("action", {})
            if action.get("type") == "stop":
                return action.get("answer")
    return None


def evaluate_session(log_file: Path, custom_tasks_dir: Path = None) -> Optional[Dict]:
    """Evaluate a single session from JSONL log."""
    events = []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        return None
    
    if not events:
        return None
    
    # Extract session info
    start_event = next((e for e in events if e.get("event") == "session_start"), None)
    if not start_event and events:
        start_event = events[0]
    
    agent_id = start_event.get("agent_id", "Unknown") if start_event else "Unknown"
    task_id = start_event.get("task_id", "Unknown") if start_event else "Unknown"
    
    task_type = detect_task_type(task_id)
    if task_type == "unknown":
        return None
    
    # Load task config
    task_config = load_task_config(task_id, custom_tasks_dir)
    if not task_config:
        return None
    
    ground_truth = task_config.get("ground_truth", {})
    
    # Common metrics
    steps = count_steps(events)
    traj_len = calculate_trajectory_length(events)
    
    result = {
        "agent": agent_id,
        "task_id": task_id,
        "task_type": task_type,
        "success": 0,
        "spl": 0.0,
        "steps": steps,
        "length": traj_len,
        "error": None
    }
    
    # Type-specific evaluation
    if task_type in ["nav", "vis"]:
        # Navigation success: final position within threshold of any target
        start_pano = task_config.get("spawn_point") or task_config.get("start_pano_id")
        target_panos = task_config.get("target_pano_ids", [])
        optimal_dist = ground_truth.get("optimal_distance_meters", 0)
        
        # Build local coord cache
        local_coords = {}
        for e in events:
            state = e.get("state", {}) or e.get("initial_state", {})
            pid = state.get("pano_id")
            lat, lng = state.get("lat"), state.get("lng")
            if pid and lat is not None and lng is not None:
                local_coords[pid] = (lat, lng)
        
        # Reconstruct path
        path = reconstruct_path_from_events(events, start_pano)
        final_pano = path[-1] if path else start_pano
        
        # Calculate error (distance to nearest target)
        min_error = float('inf')
        if final_pano and target_panos:
            for t_id in target_panos:
                d = get_distance(final_pano, t_id, local_coords)
                if d < min_error:
                    min_error = d
        
        result["error"] = min_error if min_error != float('inf') else -1
        
        if min_error <= NAV_SUCCESS_THRESHOLD_M:
            result["success"] = 1
            if optimal_dist > 0:
                result["spl"] = optimal_dist / max(traj_len, optimal_dist)
            elif optimal_dist == 0:
                result["spl"] = 1.0
    
    elif task_type == "height":
        # Height estimation: extract answer, compare with height_meters
        answer_str = get_stop_answer(events)
        predicted = extract_number(answer_str)
        gt_height = ground_truth.get("height_meters")
        
        if gt_height is None:
            # Try target_building.height
            target_building = task_config.get("target_building", {})
            gt_height = target_building.get("height")
        
        if predicted is not None and gt_height is not None and gt_height != 0:
            error_pct = abs(predicted - gt_height) / gt_height
            result["error"] = abs(predicted - gt_height)
            
            if error_pct <= HEIGHT_TOLERANCE_PCT:
                result["success"] = 1
    
    elif task_type == "dis":
        # Distance perception: extract answer, compare with distance_between_pois_m
        answer_str = get_stop_answer(events)
        predicted = extract_number(answer_str)
        gt_dist = ground_truth.get("distance_between_pois_m")
        
        if predicted is not None and gt_dist is not None:
            if gt_dist == 0:
                error_pct = 0 if predicted == 0 else float('inf')
            else:
                error_pct = abs(predicted - gt_dist) / gt_dist
            
            result["error"] = abs(predicted - gt_dist)
            
            if error_pct <= DISTANCE_TOLERANCE_PCT:
                result["success"] = 1
    
    elif task_type == "angle":
        # Angle perception: extract answer, compare with bearing_a_to_b_deg
        answer_str = get_stop_answer(events)
        predicted = extract_number(answer_str)
        gt_angle = ground_truth.get("bearing_a_to_b_deg")
        
        if predicted is not None and gt_angle is not None:
            error = calculate_angular_error(predicted, gt_angle)
            result["error"] = error
            
            if error <= ANGLE_TOLERANCE_DEG:
                result["success"] = 1
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Evaluate all task types (nav, vis, height, dis, angle)")
    parser.add_argument("--dir", type=str, required=True, help="Path to log directory")
    parser.add_argument("--tasks-dir", type=str, default=None, help="Custom tasks directory")
    args = parser.parse_args()
    
    log_dir = Path(args.dir)
    if not log_dir.exists():
        print(f"Directory not found: {log_dir}")
        return
    
    custom_tasks_dir = Path(args.tasks_dir) if args.tasks_dir else None
    
    # Find log files (prefer .jsonl)
    log_files = sorted(log_dir.glob("*.jsonl"))
    if not log_files:
        log_files = sorted(log_dir.glob("*.json"))
    
    if not log_files:
        print(f"No log files found in {log_dir}")
        return
    
    print(f"Found {len(log_files)} log files in {log_dir}")
    
    # Evaluate all sessions
    results = []
    for log_file in log_files:
        result = evaluate_session(log_file, custom_tasks_dir)
        if result:
            results.append(result)
    
    if not results:
        print("No valid sessions found.")
        return
    
    # Group by agent and type
    grouped = defaultdict(lambda: defaultdict(list))
    for r in results:
        grouped[r["agent"]][r["task_type"]].append(r)
    
    # Print table for each task type
    task_types_found = set(r["task_type"] for r in results)
    
    for task_type in sorted(task_types_found):
        print(f"\n{'=' * 110}")
        print(f"Task Type: {task_type.upper()}")
        print(f"{'=' * 110}")
        
        # Header
        header_fmt = "{:<40} | {:<5} | {:<5} | {:<7} | {:<5} | {:<6} | {:<7} | {:<7}"
        print(header_fmt.format("Agent", "Type", "Count", "SR (%)", "SPL", "Steps", "Len(m)", "Err"))
        print(header_fmt.format("-" * 5, "-" * 4, "-" * 5, "-" * 6, "-" * 5, "-" * 5, "-" * 6, "-" * 3))
        
        for agent in sorted(grouped.keys()):
            if task_type not in grouped[agent]:
                continue
            
            items = grouped[agent][task_type]
            count = len(items)
            successes = sum(1 for i in items if i["success"] == 1)
            sr = (successes / count) * 100 if count > 0 else 0
            
            avg_spl = sum(i["spl"] for i in items) / count
            avg_steps = sum(i["steps"] for i in items) / count
            avg_len = sum(i["length"] for i in items) / count
            
            # Average error (exclude -1 or None)
            valid_errors = [i["error"] for i in items if i["error"] is not None and i["error"] >= 0]
            avg_err = sum(valid_errors) / len(valid_errors) if valid_errors else -1
            avg_err_str = f"{avg_err:.1f}" if avg_err >= 0 else "-"
            
            print(header_fmt.format(
                agent[:40],
                task_type,
                str(count),
                f"{sr:.1f}",
                f"{avg_spl:.3f}",
                f"{avg_steps:.1f}",
                f"{avg_len:.1f}",
                avg_err_str
            ))
        
        print("-" * 110)
    

    # Overall summary
    print(f"\n{'=' * 110}")
    print("OVERALL SUMMARY")
    print(f"{'=' * 110}")
    print(f"Total sessions evaluated: {len(results)}")
    
    for task_type in sorted(task_types_found):
        type_results = [r for r in results if r["task_type"] == task_type]
        count = len(type_results)
        successes = sum(1 for r in type_results if r["success"] == 1)
        sr = (successes / count) * 100 if count > 0 else 0
        print(f"  {task_type}: {count} tasks, SR = {sr:.1f}%")
    
    # Calculate and print Total Score (Avg of 5 task types)
    print(f"\n{'=' * 110}")
    print("AGENT PERFORMANCE SUMMARY (Average of 5 Task Types)")
    print(f"{'=' * 110}")
    print(f"{'Agent':<40} | {'TOTAL (Avg)':<10}")
    print(f"{'-' * 40} | {'-' * 10}")

    all_task_types = ["nav", "vis", "height", "dis", "angle"]

    for agent in sorted(grouped.keys()):
        srs = []
        for t_type in all_task_types:
            if t_type in grouped[agent]:
                items = grouped[agent][t_type]
                count = len(items)
                successes = sum(1 for i in items if i["success"] == 1)
                sr = (successes / count) * 100 if count > 0 else 0.0
                srs.append(sr)
            else:
                srs.append(0.0)
        
        total_score = sum(srs) / 5.0
        print(f"{agent[:40]:<40} | {total_score:<10.1f}")
        
    print(f"{'=' * 110}")

    
    # Thresholds reference
    print("\nThresholds:")
    print(f"  nav/vis: Final distance < {NAV_SUCCESS_THRESHOLD_M}m")
    print(f"  height: Answer within ±{HEIGHT_TOLERANCE_PCT*100:.0f}% of ground truth")
    print(f"  dis: Answer within ±{DISTANCE_TOLERANCE_PCT*100:.0f}% of ground truth")
    print(f"  angle: Answer within ±{ANGLE_TOLERANCE_DEG:.0f}° of ground truth")


if __name__ == "__main__":
    main()
