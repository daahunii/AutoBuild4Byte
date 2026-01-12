import os
import shutil
import zipfile
import subprocess
from enum import Enum
from src.utils.logger import logger

class InputType(Enum):
    REMOTE = "remote"  # Git URL
    LOCAL = "local"    # Directory path
    ARCHIVE = "archive" # Zip/Tar file

class ProjectLoader:
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)

    def load_project(self, input_path: str, input_type: InputType, commit_hash: str = None) -> str:
        """
        Loads the project into the workspace and returns the absolute path to the project root in workspace.
        """
        if os.path.exists(self.workspace_path):
            shutil.rmtree(self.workspace_path)
        os.makedirs(self.workspace_path)

        logger.info(f"Loading project from {input_path} ({input_type.value}) into {self.workspace_path}")

        try:
            if input_type == InputType.REMOTE:
                self._clone_repo(input_path, commit_hash)
            elif input_type == InputType.LOCAL:
                self._copy_local(input_path)
            elif input_type == InputType.ARCHIVE:
                self._extract_archive(input_path)
            else:
                raise ValueError(f"Unknown InputType: {input_type}")
            
            logger.info("Project loaded successfully.")
            return self.workspace_path
            
        except Exception as e:
            logger.error(f"Failed to load project: {e}")
            raise

    def _clone_repo(self, repo_url: str, commit_hash: str = None):
        logger.info(f"Cloning repository: {repo_url}")
        subprocess.check_call(["git", "clone", repo_url, self.workspace_path])
        
        if commit_hash:
            logger.info(f"Checking out commit: {commit_hash}")
            subprocess.check_call(["git", "checkout", commit_hash], cwd=self.workspace_path)

    def _copy_local(self, local_path: str):
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local path not found: {local_path}")
        
        # copytree needs destination to NOT exist, but we created it in init
        # so we copy content
        for item in os.listdir(local_path):
            s = os.path.join(local_path, item)
            d = os.path.join(self.workspace_path, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

    def _extract_archive(self, archive_path: str):
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Archive file not found: {archive_path}")
        
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(self.workspace_path)
        else:
            # Assuming tar/gz for simplicity if not zip, or extend logic
            shutil.unpack_archive(archive_path, self.workspace_path)
