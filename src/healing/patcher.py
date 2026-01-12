import os
import shutil
import xml.etree.ElementTree as ET
from src.utils.logger import logger

class ProjectHealer:
    def __init__(self, project_root: str, build_info: dict):
        self.project_root = project_root
        self.build_info = build_info

    def heal(self):
        """
        Applies self-healing strategies to the project.
        """
        logger.info("Starting Self-Healing process...")
        
        self._upgrade_protocol()
        self._inject_mirror()
        self._heal_gradle_repos()
        self._heal_kotlin_plugin()
        self._heal_spring_beans_cycle()
        self._heal_websphere_support()
        self._neutralize_frontend_plugins()
        # self._redirect_archive() # TODO: Implement if needed

    def _heal_websphere_support(self):
        """
        Removes WebSphere dependencies and excludes related source files.
        """
        logger.info("Healing WebSphere support...")
        for root, dirs, files in os.walk(self.project_root):
            for file in files:
                if file.endswith(".gradle"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        modified = False
                        if "com.ibm.websphere" in content:
                            logger.info(f"Neutralizing WebSphere in {file}")
                            # Comment out dependency
                            content = content.replace('optional("com.ibm.websphere', '// optional("com.ibm.websphere')
                            content = content.replace("optional('com.ibm.websphere", "// optional('com.ibm.websphere")
                            
                            # Add excludes
                            exclude_logic = "\n// Exclude missing WebSphere classes\nsourceSets.main.java.exclude '**/WebSphere*'\nsourceSets.test.java.exclude '**/WebSphere*'\n"
                            if "sourceSets.main.java.exclude '**/WebSphere*'" not in content:
                                content += exclude_logic
                            modified = True
                        
                        if modified:
                             with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                                
                    except Exception as e:
                        logger.warning(f"Failed to heal WebSphere in {file}: {e}")

    def _neutralize_frontend_plugins(self):
        """
        Removes frontend-maven-plugin and exec-maven-plugin from web-console/pom.xml.
        """
        logger.info("Neutralizing frontend plugins...")
        
        # Register namespace to avoid ns0 prefix
        ET.register_namespace('', "https://maven.apache.org/POM/4.0.0")
        
        for root, dirs, files in os.walk(self.project_root):
            if "pom.xml" in files:
                file_path = os.path.join(root, "pom.xml")
                
                # Identify web-console pom
                is_target = False
                if os.path.basename(root) == "web-console":
                    is_target = True
                
                # Double check parsing
                if not is_target:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            if "<artifactId>druid-console</artifactId>" in f.read():
                                is_target = True
                    except: pass
                
                if is_target:
                    try:
                        tree = ET.parse(file_path)
                        root_elem = tree.getroot()
                        
                        # Handle namespace
                        ns = {'mvn': 'https://maven.apache.org/POM/4.0.0'}
                        
                        # Find plugins section
                        plugins_container = root_elem.find(".//mvn:build/mvn:plugins", ns)
                        if plugins_container is not None:
                            to_remove = []
                            for plugin in plugins_container.findall("mvn:plugin", ns):
                                artifact_id = plugin.find("mvn:artifactId", ns)
                                a_text = artifact_id.text if artifact_id is not None else ""
                                
                                if "frontend-maven-plugin" in a_text or "exec-maven-plugin" in a_text:
                                    to_remove.append(plugin)
                            
                            if to_remove:
                                for p in to_remove:
                                    plugins_container.remove(p)
                                    logger.info(f"Removed plugin {p.find('mvn:artifactId', ns).text} from {file_path}")
                                
                                tree.write(file_path, encoding='UTF-8', xml_declaration=True)
                                logger.info(f"Successfully patched {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to neutralize plugins in {file_path}: {e}")

    def _upgrade_protocol(self):
        """
        Replaces http:// with https:// in all build files.
        """
        build_files = self.build_info.get("all_build_files", [])
        count = 0
        for file_path in build_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "http://" in content:
                    new_content = content.replace("http://", "https://")
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    count += 1
                    logger.info(f"Upgraded protocol in {os.path.basename(file_path)}")
            except Exception as e:
                logger.warning(f"Failed to patch {file_path}: {e}")
        
        if count > 0:
            logger.info(f"Fixed insecure protocols in {count} files.")

    def _collect_https_repos(self):
        """
        Scans all pom.xml files to find repositories with HTTPS URLs.
        Returns a list of repository IDs to exclude from the mirror.
        """
        https_repo_ids = set()
        for root, dirs, files in os.walk(self.project_root):
            if "pom.xml" in files:
                file_path = os.path.join(root, "pom.xml")
                try:
                    # Parse XML to find <repository> tags
                    tree = ET.parse(file_path)
                    root_elem = tree.getroot()
                    
                    # Namespace handling: remove namespace for easier search
                    # However, iterating without namespace map is tricky in ET if not careful.
                    # We iterate all elements and check tag suffix.
                    for elem in root_elem.iter():
                        if elem.tag.endswith('repository'):
                            url = None
                            repo_id = None
                            for child in elem:
                                if child.tag.endswith('url') and child.text:
                                    url = child.text.strip()
                                if child.tag.endswith('id') and child.text:
                                    repo_id = child.text.strip()
                            
                            if url and repo_id and url.startswith('https://'):
                                https_repo_ids.add(repo_id)
                                logger.debug(f"Found HTTPS repo: {repo_id} ({url})")
                except Exception as e:
                    # Not all pom.xml files are valid or parseable, ignore errors
                    pass
        return list(https_repo_ids)

    def _inject_mirror(self):
        """
        Creates a custom settings.xml with Google Maven Mirror.
        """
        settings_path = os.path.join(self.project_root, "settings.xml")
        
        # Collect HTTPS repos to exclude from mirror
        https_repos = self._collect_https_repos()
        mirror_of = "*"
        if https_repos:
            # Exclude them from mirror so Maven uses them directly
            mirror_of = "*,!" + ",!".join(https_repos)
            logger.info(f"Excluding HTTPS repos from mirror: {https_repos}")
        
        mirror_content = f"""<settings>
  <mirrors>
    <mirror>
      <id>google-maven-central</id>
      <name>Google Maven Central</name>
      <url>https://maven-central.storage-download.googleapis.com/maven2/</url>
      <mirrorOf>{mirror_of}</mirrorOf>
    </mirror>
  </mirrors>
</settings>"""

        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                f.write(mirror_content)
            logger.info(f"Injected Google Maven Mirror into {settings_path}")
        except Exception as e:
            logger.error(f"Failed to inject mirror: {e}")

    def _heal_gradle_repos(self):
        """
        Patches build.gradle files to fix broken repositories (e.g., repo.spring.io).
        """
        logger.info("Healing Gradle repositories...")
        build_files = []
        logger.info(f"Scanning for .gradle files in: {self.project_root}")
        for root, dirs, files in os.walk(self.project_root):
            for file in files:
                if file.endswith(".gradle"):
                    full_path = os.path.join(root, file)
                    build_files.append(full_path)
                    logger.info(f"Found .gradle file: {full_path}")
        
        # Hardcode check for ide.gradle to be safe
        ide_gradle = os.path.join(self.project_root, "buggy", "gradle", "ide.gradle")
        if os.path.exists(ide_gradle) and ide_gradle not in build_files:
             logger.info(f"Explicitly adding ide.gradle from {ide_gradle}")
             build_files.append(ide_gradle)
        elif not os.path.exists(ide_gradle):
             # Try without 'buggy' in path?
             ide_gradle_flat = os.path.join(self.project_root, "gradle", "ide.gradle")
             if os.path.exists(ide_gradle_flat) and ide_gradle_flat not in build_files:
                  logger.info(f"Explicitly adding ide.gradle from {ide_gradle_flat}")
                  build_files.append(ide_gradle_flat)
        
        for file_path in build_files:
            logger.info(f"Processing {file_path}")
            # if not file_path.endswith(".gradle"): continue # Already filtered
                
            try:
                # Read content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                original_content = content
                
                # 1. Inject central repos if 'repositories {' exists
                if "repositories {" in content:
                    # Naively inject at the start of repositories block
                    # Not perfect if multiple blocks, but good enough to ensure they exist
                    # We use simple string replace for the first occurrence or just regex
                    # Actually, let's just make sure they are present.
                    # But the critical part is REMOVING the bad ones.
                    
                    # 2. Remove broken repos using regex
                    # Pattern: maven { url '...repo.spring.io...' }
                    # We handle single quotes and double quotes
                    
                    # Regex to match: maven\s*\{\s*url\s*['"].*?repo\.spring\.io.*?['"]\s*\}
                    # This handles one-liners. Multi-liners are harder but usually they are one-liners in this project.
                    
                    import re
                    pattern = r"maven\s*\{\s*url\s*['\"].*?repo\.spring\.io.*?['\"]\s*\}"
                    
                    # Check if we find matches
                    matches = re.findall(pattern, content)
                    if matches:
                        logger.info(f"Found {len(matches)} broken repos in {os.path.basename(file_path)}")
                        content = re.sub(pattern, '', content)
                        
                    # 3. Remove broken snapshot plugins (causing 404s)
                    # Pattern: classpath('io.spring.gradle:spring-build-conventions:...')
                    # Pattern: classpath('io.spring.gradle:docbook-reference-plugin:...')
                    # Pattern: classpath('io.spring.gradle:propdeps-plugin:...')
                    # Pattern: classpath('io.spring.gradle:spring-io-plugin:...')
                    
                    plugin_patterns = [
                        r"classpath\s*\(\s*['\"]io\.spring\.gradle:spring-build-conventions:.*?['\"]\s*\)(\s*\{.*?\})?",
                        r"classpath\s*\(\s*['\"]io\.spring\.gradle:docbook-reference-plugin:.*?['\"]\s*\)",
                        r"classpath\s*\(\s*['\"]io\.spring\.gradle:propdeps-plugin:.*?['\"]\s*\)",
                        r"classpath\s*\(\s*['\"]io\.spring\.gradle:spring-io-plugin:.*?['\"]\s*\)",
                        r"classpath\s*\(\s*['\"]org\.springframework\.build\.gradle:propdeps-plugin:.*?['\"]\s*\)"
                    ]
                    
                    for p in plugin_patterns:
                        plugin_matches = re.findall(p, content, re.DOTALL) # DOTALL for multi-line exclude blocks
                        if plugin_matches:
                            logger.info(f"Removing broken plugin usage in {os.path.basename(file_path)}")
                            content = re.sub(p, "", content, flags=re.DOTALL)

                    # 4. Remove 'apply plugin: "propdeps"' and shim it
                    if 'apply plugin: "propdeps"' in content or "apply plugin: 'propdeps'" in content:
                        logger.info(f"Shimming propdeps in {os.path.basename(file_path)}")
                        shim_code = """
                        // Shim for removed propdeps plugin
                        configurations {
                            optional
                            provided
                        }
                        sourceSets.main.compileClasspath += configurations.optional
                        sourceSets.main.compileClasspath += configurations.provided
                        sourceSets.main.runtimeClasspath += configurations.optional
                        sourceSets.main.runtimeClasspath += configurations.provided
                        sourceSets.test.compileClasspath += configurations.optional
                        sourceSets.test.compileClasspath += configurations.provided
                        sourceSets.test.runtimeClasspath += configurations.optional
                        sourceSets.test.runtimeClasspath += configurations.provided
                        """
                        content = content.replace('apply plugin: "propdeps"', shim_code)
                        content = content.replace("apply plugin: 'propdeps'", shim_code)

                    # Also remove the apply plugin line if it exists
                    # apply plugin: 'io.spring.convention.root'
                    content = re.sub(r"apply\s+plugin:\s*['\"]io\.spring\.convention\.root['\"]", "", content)

                if "ide.gradle" in file_path:
                    logger.info(f"DEBUG: Content start of ide.gradle: {content[:200]}")
                    if "propdeps-eclipse" in content:
                        logger.info("DEBUG: Found 'propdeps-eclipse' in content")
                    else:
                        logger.info("DEBUG: 'propdeps-eclipse' NOT found in content")

                # Remove other propdeps related plugins (use string replace for safety)
                # Try naive replacement 
                if "propdeps-eclipse" in content:
                     logger.info(f"Removing propdeps-eclipse from {file_path}")
                     content = content.replace('apply plugin: "propdeps-eclipse"', 'apply plugin: "eclipse"')
                     content = content.replace("apply plugin: 'propdeps-eclipse'", "apply plugin: 'eclipse'")
                     # Also try regex fall-back just in case of weird whitespace
                     content = re.sub(r"apply\s+plugin:\s*['\"]propdeps-eclipse['\"]", "apply plugin: 'eclipse'", content)

                if "propdeps-idea" in content:
                    logger.info(f"Removing propdeps-idea from {file_path}")
                    content = content.replace('apply plugin: "propdeps-idea"', 'apply plugin: "idea"')
                    content = content.replace("apply plugin: 'propdeps-idea'", "apply plugin: 'idea'")
                    
                if "propdeps-maven" in content:
                    logger.info(f"Removing propdeps-maven from {file_path}")
                    content = content.replace('apply plugin: "propdeps-maven"', 'apply plugin: "maven"')
                    content = content.replace("apply plugin: 'propdeps-maven'", "apply plugin: 'maven'")
                
                # 3. Inject mavenCentral if not present (simple check)
                if "mavenCentral()" not in content:
                     # This is a bit risky to blindly replace, but let's try injecting into repositories block
                     pass 
                
                # Use the previous injection logic via simple replace if we didn't do it yet
                # Or simply:
                if content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"Patched repositories in {os.path.basename(file_path)}")
                    
            except Exception as e:
                logger.warning(f"Failed to match gradle repos in {file_path}: {e}")

    def _heal_kotlin_plugin(self):
        """
        Upgrades Kotlin plugin version to 1.3.72 to fix compatibility with Gradle 6.9.4.
        """
        logger.info("Healing Kotlin plugin version...")
        build_files = self.build_info.get("all_build_files", [])
        
        for file_path in build_files:
            if not file_path.endswith("build.gradle"):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                original_content = content
                
                # Upgrade plugin version
                if 'id "org.jetbrains.kotlin.jvm" version "1.2.70"' in content:
                    content = content.replace(
                        'id "org.jetbrains.kotlin.jvm" version "1.2.70"',
                        'id "org.jetbrains.kotlin.jvm" version "1.3.72"'
                    )
                
                # Upgrade kotlinVersion variable
                if 'kotlinVersion        = "1.2.71"' in content:
                    content = content.replace(
                        'kotlinVersion        = "1.2.71"',
                        'kotlinVersion        = "1.3.72"'
                    )
                
                if content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"Upgraded Kotlin plugin in {os.path.basename(file_path)}")
                    
            except Exception as e:
                logger.warning(f"Failed to patch Kotlin plugin in {file_path}: {e}")

    def _heal_spring_beans_cycle(self):
        """
        Fixes circular dependency in spring-beans/spring-beans.gradle
        between compileGroovy, compileJava, and compileKotlin.
        """
        logger.info("Healing spring-beans circular dependency...")
        # Locate spring-beans.gradle
        target_file = None
        for root, dirs, files in os.walk(self.project_root):
            if "spring-beans.gradle" in files:
                target_file = os.path.join(root, "spring-beans.gradle")
                break
        
        if not target_file:
            logger.warning("Could not find spring-beans.gradle")
            return

        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # The problematic code relying on internal/old API
            target_block = """def deps = compileGroovy.taskDependencies.immutableValues + compileGroovy.taskDependencies.mutableValues
compileGroovy.dependsOn = deps - "compileJava" """
            
            target_block_normalized = target_block.strip()
            
            # Simple replace doesn't work well with whitespace variation, 
            # let's try a more specific match or just line replacement if we are confident.
            # The lines are at the end of the file.
            
            # We can use regex to match the lines.
            import re
            pattern = r"def\s+deps\s*=\s*compileGroovy\.taskDependencies\.immutableValues\s*\+\s*compileGroovy\.taskDependencies\.mutableValues\s*compileGroovy\.dependsOn\s*=\s*deps\s*-\s*['\"]compileJava['\"]"
            
            # Actually, let's constructs the replacement string.
            replacement = """// Fixed circular dependency by filtering deps cleanly
compileGroovy.dependsOn = compileGroovy.taskDependencies.getDependencies(compileGroovy).findAll { it.name != 'compileJava' }"""
            
            # Current content in file might be the original or the patched one.
            # We want to force the robust afterEvaluate version.
            
            # The pattern for the ORIGINAL buggy code
            orig_pattern_regex = r"def\s+deps\s*=\s*compileGroovy\.taskDependencies\.immutableValues\s*\+\s*compileGroovy\.taskDependencies\.mutableValues\s+compileGroovy\.dependsOn\s*=\s*deps\s*-\s*['\"]compileJava['\"]"
            
            # The pattern for the PREVIOUSLY PATCHED code (any version of it)
            patched_pattern_regex = r"// Fixed circular dependency by filtering deps cleanly.*compileGroovy\.dependsOn\s*=\s*compileGroovy\.taskDependencies\.getDependencies\(compileGroovy\)\.findAll\s*\{\s*it\.name\s*!=\s*['\"]compileJava['\"]\s*\}\s*(\}\s*)?"

            # Stronger replacement with afterEvaluate breaking both sides of the cycle
            robust_replacement = """// Fixed circular dependency by filtering deps cleanly
afterEvaluate {
    // Break Groovy -> Java
    compileGroovy.setDependsOn(compileGroovy.taskDependencies.getDependencies(compileGroovy).findAll { it.name != 'compileJava' })
    // Break Java -> Kotlin (since Java source is empty, it needs no deps)
    compileJava.setDependsOn([])
}"""

            # Note: patched_pattern_regex needs to handle potential newlines and the previous afterEvaluate block structure
            # To be safe, let's use a simpler check for finding if we need to replace a previous patch.
            
            if "Fixed circular dependency by filtering deps cleanly" in content:
                # Identify the start index
                start_marker = "// Fixed circular dependency by filtering deps cleanly"
                idx = content.find(start_marker)
                
                # We need to find the end of the block.
                # If it was the one-liner:
                # ends at newline.
                # If it was the afterEvaluate block:
                # ends at '}'
                
                # Simpler approach: Replace the known previous variants with the new one.
                # Variant 1: One-liner
                v1 = """// Fixed circular dependency by filtering deps cleanly
compileGroovy.dependsOn = compileGroovy.taskDependencies.getDependencies(compileGroovy).findAll { it.name != 'compileJava' }"""
                
                # Variant 2: afterEvaluate block (previous attempt)
                v2 = """// Fixed circular dependency by filtering deps cleanly
afterEvaluate {
    compileGroovy.dependsOn = compileGroovy.taskDependencies.getDependencies(compileGroovy).findAll { it.name != 'compileJava' }
}"""

                if v2 in content:
                    content = content.replace(v2, robust_replacement)
                    logger.info("Upgraded existing afterEvaluate patch in spring-beans.gradle")
                elif v1 in content:
                     content = content.replace(v1, robust_replacement)
                     logger.info("Upgraded existing one-liner patch to afterEvaluate/double-break in spring-beans.gradle")
                else:
                    # Maybe regex match for safety if slight whitespace diffs
                     if re.search(patched_pattern_regex, content, re.DOTALL):
                         content = re.sub(patched_pattern_regex, robust_replacement, content, flags=re.DOTALL)
                         logger.info("Regex replaced previous patch in spring-beans.gradle")
                     else:
                         logger.warning("Could not cleanly identify previous patch to upgrade. Appending anyway?")
                         # If we can't find it but the marker is there, maybe we manually deleted lines?
                         # Let's fallback to replacing the original pattern if present, else just leave it (risky).
                         pass

            elif re.search(orig_pattern_regex, content):
                content = re.sub(orig_pattern_regex, robust_replacement, content)
                logger.info(f"Replaced original dependency logic with double-break afterEvaluate in {target_file}")
            else:
                 # Fallback checks (string based) if regex fails due to whitespace
                 if 'compileGroovy.dependsOn = deps - "compileJava"' in content:
                      content = content.replace(
                        'def deps = compileGroovy.taskDependencies.immutableValues + compileGroovy.taskDependencies.mutableValues',
                        '// Removed old logic'
                      )
                      content = content.replace(
                        'compileGroovy.dependsOn = deps - "compileJava"',
                        robust_replacement
                      )
                      logger.info("Used fallback string replacement.")

            if content != original_content:
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info("Successfully patched spring-beans.gradle")
                
        except Exception as e:
            logger.warning(f"Failed to specific spring-beans patch: {e}")
