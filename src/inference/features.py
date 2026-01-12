import os
import javalang
from src.utils.logger import logger

class FeatureExtractor:
    def __init__(self, project_root: str):
        self.project_root = project_root

    def detect_java_features(self):
        """
        Scans all java files and returns the minimum required Java version based on features.
        Returns: int (e.g., 7, 8, 11) or None
        """
        max_version = 0

        for root, _, files in os.walk(self.project_root):
            for file in files:
                if file.endswith(".java"):
                    path = os.path.join(root, file)
                    version = self._analyze_file(path)
                    if version > max_version:
                        max_version = version
        
        return max_version if max_version > 0 else None

    def _analyze_file(self, file_path: str) -> int:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Lightweight regex/text search for features that javalang might miss or fail to parse if version is too new
            if "var " in content: 
                # Very naive check for var (Java 10+). Real parsing is better but javalang parser needs to be robust.
                # Let's rely on javalang for structural things and text for keywords if needed.
                pass

            try:
                tree = javalang.parse.parse(content)
            except javalang.parser.JavaSyntaxError:
                # If syntax error, it might be a newer version than javalang supports, or just bad code.
                # javalang supports up to Java 8 mainly.
                return 0

            # Scan tree for features
            # try-with-resources -> Java 7
            for _, node in tree.filter(javalang.tree.TryResource):
                return 7
            
            # Lambda -> Java 8
            for _, node in tree.filter(javalang.tree.LambdaExpression):
                return 8
                
            # MethodReference -> Java 8
            for _, node in tree.filter(javalang.tree.MethodReference):
                return 8

        except Exception as e:
            # logger.warning(f"Failed to parse {file_path}: {e}")
            pass
        
        return 0
