import json
import os
from typing import Any, Dict, List

FILE_NAME = ".github/scalene.json"


def cleanup_scalene_json():
    """Clean up scalene.json to keep only metrics-related data."""
    try:
        # check if file exists first
        if not os.path.exists(FILE_NAME):
            print(f"{FILE_NAME} does not exist")
            return

        with open(FILE_NAME, "r") as f:
            data = json.load(f)

        # Keep only essential metrics
        cleaned_data: Dict[str, Any] = {
            "max_footprint_mb": data.get("max_footprint_mb", 0),
            "files": {},
        }

        # Process only files with functions
        for file_path, file_data in data.get("files", {}).items():
            if "functions" in file_data:
                cleaned_functions: List[Dict[str, Any]] = []
                for func in file_data["functions"]:
                    # Keep only if it has CPU or memory metrics
                    if any(
                        func.get(metric)
                        for metric in [
                            "n_cpu_percent_c",
                            "n_cpu_percent_python",
                            "n_sys_percent",
                            "n_malloc_mb",
                        ]
                    ):
                        cleaned_functions.append(
                            {
                                "line": func.get("line", ""),
                                "n_cpu_percent_c": func.get("n_cpu_percent_c", 0),
                                "n_cpu_percent_python": func.get(
                                    "n_cpu_percent_python", 0
                                ),
                                "n_sys_percent": func.get("n_sys_percent", 0),
                                "n_malloc_mb": func.get("n_malloc_mb", 0),
                            }
                        )

                if cleaned_functions:
                    cleaned_data["files"][file_path] = {"functions": cleaned_functions}

        # Write cleaned data back to file
        with open(FILE_NAME, "w") as f:
            json.dump(cleaned_data, f, indent=2)

        print(f"Successfully cleaned up {FILE_NAME}")

    except FileNotFoundError:
        print(f"{FILE_NAME} not found")
    except Exception as e:
        print(f"Error cleaning up {FILE_NAME}: {e}")


if __name__ == "__main__":
    cleanup_scalene_json()
