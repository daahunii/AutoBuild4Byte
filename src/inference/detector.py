import os
from lxml import etree
from src.utils.logger import logger
from src.inference.features import FeatureExtractor

class EnvironmentDetector:
    def __init__(self, project_root: str, build_info: dict):
        self.project_root = project_root
        self.build_info = build_info
        self.feature_extractor = FeatureExtractor(project_root)

    def detect(self):
        """
        Detects the best matching environment configuration.
        Returns: dict {"jdk_version": int, "build_tool_version": str}
        """
        logger.info("Starting Environment Inference...")
        
        # 1. Detect JDK Version
        jdk_from_config = self._detect_jdk_from_config()
        jdk_from_code = self.feature_extractor.detect_java_features()
        
        logger.info(f"JDK Inference - Config: {jdk_from_config}, Code: {jdk_from_code}")
        
        # Policy: Max(Config, Code, Default=8)
        jdk_version = max(filter(None, [jdk_from_config, jdk_from_code, 8]))
        
        # 2. Detect Build Tool Version
        build_tool = self.build_info.get("build_tool")
        if build_tool == "gradle":
            build_tool_version = "6.9.4" # Stable version compatible with Java 8-15
        else:
            build_tool_version = "3.8.6" # Default safe choice for Maven
        
        # Check wrapper
        wrapper_props = os.path.join(self.project_root, ".mvn", "wrapper", "maven-wrapper.properties")
        if os.path.exists(wrapper_props):
            # Parse wrapper to find version
            pass

        return {
            "jdk_version": int(jdk_version),
            "build_tool": self.build_info.get("build_tool"),
            "build_tool_version": build_tool_version
        }

    def _detect_jdk_from_config(self) -> int:
        root_build_file = self.build_info.get("root_build_file")
        if not root_build_file or not root_build_file.endswith("pom.xml"):
            return None
        
        try:
            tree = etree.parse(root_build_file)
            root = tree.getroot()
            ns = root.nsmap.get(None)
            ns_prefix = f"{{{ns}}}" if ns else ""
            
            # Check properties
            # maven.compiler.source, maven.compiler.target
            # java.version
            
            properties = root.find(f"{ns_prefix}properties")
            if properties is not None:
                source = properties.find(f"{ns_prefix}maven.compiler.source")
                if source is not None and source.text:
                    return self._parse_java_version(source.text)
                
                target = properties.find(f"{ns_prefix}maven.compiler.target")
                if target is not None and target.text:
                    return self._parse_java_version(target.text)

            # Check configuration in plugins
            # This requires deep XML walking, simplified here for prototype
            
        except Exception as e:
            logger.warning(f"Failed to parse pom.xml for JDK version: {e}")
            
        return None

    def _parse_java_version(self, version_str: str) -> int:
        try:
            if version_str.startswith("1."):
                return int(version_str.split(".")[1])
            return int(version_str)
        except:
            return None
