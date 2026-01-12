import sys
import os
import argparse
import docker
# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.logger import logger
from src.acquisition.loader import ProjectLoader, InputType
from src.discovery.scanner import ProjectScanner

def check_prerequisites() -> bool:
    """
    Checks if necessary prerequisites (Docker) are available.
    """
    try:
        client = docker.from_env()
        client.ping()
        logger.info("Docker is running.")
        return True
    except docker.errors.DockerException:
        logger.error("Docker is not accessible. Please ensure Docker Desktop/Daemon is running.")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking prerequisites: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="AutoBuild4Byte: Automated Builder for Recovering Bytecode")
    parser.add_argument("--type", required=True, choices=["remote", "local", "archive"], help="Input input type")
    parser.add_argument("--path", required=True, help="Input path (URL, Dir, or File)")
    parser.add_argument("--commit", help="Commit hash (for remote type)")
    parser.add_argument("--workspace", default="workspace", help="Workspace directory")
    parser.add_argument("--output", default="output", help="Output directory for artifacts")
    
    args = parser.parse_args()
    
    # Phase 1: Acquisition
    logger.info("=== Phase 1: Acquisition ===")
    loader = ProjectLoader(args.workspace)
    try:
        input_type = InputType(args.type)
        project_root = loader.load_project(args.path, input_type, args.commit)
    except Exception as e:
        logger.error(f"Acquisition failed: {e}")
        return

    # Phase 0: Pre-flight Checks
    logger.info("=== Phase 0: Pre-flight Checks ===")
    if not check_prerequisites():
         logger.error("Pre-flight checks failed. Please ensure Docker is running.")
         sys.exit(1)

    # Phase 1: Discovery
    logger.info("=== Phase 1: Discovery ===")
    scanner = ProjectScanner(project_root)
    project_info = scanner.scan()
    
    if not project_info:
        logger.error("Project discovery failed. No build files found.")
        return

    logger.info(f"Discovery Result: {project_info}")

    # Phase 2: Inference
    logger.info("=== Phase 2: Inference ===")
    from src.inference.detector import EnvironmentDetector
    
    detector = EnvironmentDetector(project_root, project_info)
    env_config = detector.detect()
    
    
    logger.info(f"Inferred Environment: {env_config}")

    # Phase 3: Healing
    logger.info("=== Phase 3: Healing ===")
    from src.healing.patcher import ProjectHealer
    
    
    healer = ProjectHealer(project_root, project_info)
    healer.heal()
    
    # Phase 4: Execution & Dynamic Healing
    logger.info("=== Phase 4: Execution & Dynamic Healing ===")
    from src.execution.docker_manager import DockerManager
    from src.healing.llm_healer import LLMHealer
    
    # Calculate relative path from workspace root to build file directory
    root_build_file = project_info.get("root_build_file")
    build_dir = os.path.dirname(root_build_file)
    build_relative_path = os.path.relpath(build_dir, project_root)
    
    if build_relative_path == ".":
        build_relative_path = ""
        
    logger.info(f"Build Root: {build_dir} (Relative: {build_relative_path})")
    
    builder = DockerManager(project_root, env_config, build_relative_path)
    llm_healer = LLMHealer(project_root)
    
    # Create output directory if it doesn't exist
    output_dir = os.path.abspath(args.output)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    MAX_RETRIES = 10
    retry_count = 0
    build_success = False
    
    while retry_count <= MAX_RETRIES:
        logger.info(f"--- Execution Attempt {retry_count + 1}/{MAX_RETRIES + 1} ---")
        
        success, logs = builder.execute(output_path=output_dir)
        
        if success:
            logger.info("Build Cycle Success!")
            build_success = True
            break
        else:
            logger.warning("Build Cycle Failed.")
            if retry_count < MAX_RETRIES:
                logger.info("Attempting LLM Healing...")
                healed = llm_healer.heal(logs)
                if healed:
                    logger.info("Healing applied. Retrying build...")
                    retry_count += 1
                    continue
                else:
                    logger.error("LLM Healing failed or no solution found. Stopping.")
                    break
            else:
                logger.error("Max retries reached. Stopping.")
                break

    if not build_success:
        logger.error("Final Result: Build Failed.")
        sys.exit(1)
    else:
        logger.info("Final Result: Build Succeeded.")

if __name__ == "__main__":
    main()
