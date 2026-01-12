import os
import glob
from lxml import etree
from src.utils.logger import logger

class ProjectScanner:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.build_files = []
        self.root_build_file = None
        self.build_tool = None # "maven" or "gradle"

    def scan(self):
        """
        Scans the project for build files and determines the root build file.
        """
        logger.info(f"Scanning project in: {self.project_root}")
        
        maven_files = self._find_files("pom.xml")
        gradle_files = self._find_files("build.gradle") + self._find_files("build.gradle.kts")

        if maven_files:
            self.build_tool = "maven"
            self.build_files = maven_files
            self.root_build_file = self._find_root_pom(maven_files)
        elif gradle_files:
            self.build_tool = "gradle"
            self.build_files = gradle_files
            self.root_build_file = self._find_root_gradle(gradle_files)
        else:
            logger.warning("No build files found!")
            return None

        logger.info(f"Identified Build Tool: {self.build_tool}")
        logger.info(f"Root Build File: {self.root_build_file}")
        
        return {
            "build_tool": self.build_tool,
            "root_build_file": self.root_build_file,
            "all_build_files": self.build_files
        }

    def _find_files(self, filename):
        matches = []
        for root, _, files in os.walk(self.project_root):
            if filename in files:
                matches.append(os.path.join(root, filename))
        return matches

    def _find_root_pom(self, output_files):
        # Heuristic 1: If pom.xml exists at project root, it's likely the root
        root_pom = os.path.join(self.project_root, "pom.xml")
        if root_pom in output_files:
            return root_pom
        
        # Heuristic 2: Find file with <modules> but no <parent> (or parent is external) (simplified)
        # For now, return the one with shortest path
        return min(output_files, key=len)

    def _find_root_gradle(self, output_files):
        # Heuristic: build.gradle at root
        root_gradle = os.path.join(self.project_root, "build.gradle")
        if root_gradle in output_files:
            return root_gradle
        
        return min(output_files, key=len)
