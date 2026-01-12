import os
import docker
import jinja2
import shutil
from src.utils.logger import logger

class DockerManager:
    def __init__(self, workspace_path: str, env_config: dict, build_relative_path: str = ""):
        self.workspace_path = workspace_path
        self.env_config = env_config
        self.build_relative_path = build_relative_path
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException:
            self.client = None
            logger.warning("Docker is not running or not accessible. Sandbox execution will be skipped.")
        self.image_tag = "autobuild_agent:latest"

    def execute(self, output_path: str = None) -> tuple[bool, str]:
        """
        Orchestrates the build process and extracts artifacts.
        Returns:
            (success: bool, logs: str)
        """
        if not self.client:
            logger.error("Skipping Docker execution: Docker client not initialized.")
            return False, "Docker client not initialized"

        logs = ""
        try:
            self._generate_dockerfile()
            self._build_image()
            self._clean_target_on_host()
            exit_code, build_logs = self._run_build()
            logs = build_logs
            
            if exit_code == 0:
                if output_path:
                    self._extract_artifacts(output_path)
                return True, logs
            else:
                return False, logs
                
        except Exception as e:
            logger.error(f"Execution failed with exception: {e}")
            return False, str(e)

    def _clean_target_on_host(self):
        """
        Cleans the target directory on the host to avoid Docker permission issues.
        """
        target_dir_mvn = os.path.join(self.workspace_path, self.build_relative_path, "target")
        target_dir_gradle = os.path.join(self.workspace_path, self.build_relative_path, "build")
        
        for target_dir in [target_dir_mvn, target_dir_gradle]:
            if os.path.exists(target_dir):
                logger.info(f"Cleaning target directory on host: {target_dir}")
                try:
                    shutil.rmtree(target_dir)
                except Exception as e:
                    logger.warning(f"Failed to clean target directory on host: {e}")

    def _generate_dockerfile(self):
        logger.info("Generating Dockerfile...")
        template_loader = jinja2.FileSystemLoader(searchpath=os.path.join(os.path.dirname(__file__), "templates"))
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template("Dockerfile.j2")
        
        dockerfile_content = template.render(
            jdk_version=self.env_config.get("jdk_version", 8),
            build_tool=self.env_config.get("build_tool", "maven"),
            build_tool_version=self.env_config.get("build_tool_version", "4.10.3")
        )
        
        with open(os.path.join(self.workspace_path, "Dockerfile"), "w") as f:
            f.write(dockerfile_content)
        
        logger.info(f"Dockerfile generated at {self.workspace_path}/Dockerfile")

    def _build_image(self):
        logger.info(f"Building Docker image {self.image_tag}...")
        try:
            # self.client.images.build(path=self.workspace_path, tag=self.image_tag, rm=True)
            # Using low-level API to stream logs if needed, but simple build is fine
            image, build_logs = self.client.images.build(path=self.workspace_path, tag=self.image_tag)
            for chunk in build_logs:
                if 'stream' in chunk:
                    logger.debug(chunk['stream'].strip())
            logger.info("Docker image built successfully.")
        except docker.errors.BuildError as e:
            logger.error(f"Docker build failed: {e}")
            for line in e.build_log:
                if 'stream' in line:
                    logger.error(line['stream'].strip())
            raise

    def _run_build(self):
        """
        Runs the build in the container.
        Returns:
            (exit_code: int, logs: str)
        """
        logger.info("Running build in container...")
        # Skip 'clean' inside container to avoid permission issues with mounted volumes
        build_tool = self.env_config.get("build_tool", "maven")
        
        # Generate/Copy init.gradle for Gradle builds
        if build_tool == "gradle":
            init_gradle_src = os.path.join(os.path.dirname(__file__), "templates", "init.gradle")
            # We copy it to workspace first (optional, for debugging)
            init_gradle_dst = os.path.join(self.workspace_path, "init.gradle")
            if os.path.exists(init_gradle_src):
                shutil.copy(init_gradle_src, init_gradle_dst)
                logger.info(f"Copied init.gradle to {init_gradle_dst}")
                
            else:
                logger.warning("init.gradle template not found, skipping injection.")
            
            # Use standard command
            cmd = "gradle compileJava -x test --stacktrace --info"
            
        elif build_tool == "maven":
            # Use 'package' instead of 'compile' to ensure test-jars are generated for multi-module dependencies
            # -T 1C: Run builds in parallel (1 thread per core) to speed up execution
            cmd = "mvn package -DskipTests -T 1C"
            
            exclusions = []
            build_root = os.path.join(self.workspace_path, self.build_relative_path) if self.build_relative_path else self.workspace_path
            
            if os.path.exists(os.path.join(build_root, "distribution")):
                exclusions.append("!distribution")
            
            if exclusions:
                cmd += f" -pl {','.join(exclusions)}"
            
            # Add skip flags as a robust fallback
            cmd += " -Dskip.npm=true -Dskip.node=true -Dskip.installnodenpm=true"

            if os.path.exists(os.path.join(self.workspace_path, "settings.xml")):
                cmd += " -s /app/settings.xml"
        else:
            cmd = "echo 'Unknown build tool'"
        
        # Mount settings.xml if it exists and init.gradle
        volumes = {
            self.workspace_path: {'bind': '/app', 'mode': 'rw'}
        }
        
        if build_tool == "gradle" and os.path.exists(init_gradle_dst):
             # Bind init.gradle to global init.d
             volumes[init_gradle_dst] = {'bind': '/root/.gradle/init.d/autobuild.gradle', 'mode': 'ro'}
        
        # Mount settings.xml if it exists to /root/.m2/settings.xml for global effect
        settings_xml_path = os.path.join(self.workspace_path, "settings.xml")
        if os.path.exists(settings_xml_path):
             volumes[settings_xml_path] = {'bind': '/root/.m2/settings.xml', 'mode': 'ro'}

        # explicit container name to ensure we can clean it up
        container_name = "autobuild_sandbox"
        
        # Clean up any existing container with the same name first
        self._cleanup_container(container_name)

        container = None
        logs = []
        exit_code = -1
        
        try:
            container = self.client.containers.run(
                self.image_tag,
                name=container_name,
                command=cmd,
                volumes=volumes,
                working_dir=f"/app/{self.build_relative_path}".rstrip("/"),
                detach=True,
                user=os.getuid() # Run as host user to avoid permission issues
            )
            
            for line in container.logs(stream=True):
                decoded_line = line.decode('utf-8').strip()
                logger.info(f"[Container] {decoded_line}")
                logs.append(decoded_line)
            
            result = container.wait()
            exit_code = result['StatusCode']
            
            if exit_code == 0:
                logger.info("Build succeeded!")
            else:
                logger.error(f"Build failed with status code {exit_code}")
                # We do NOT raise exception here, just return logs and status
                
        except Exception as e:
            logger.error(f"Container run failed: {e}")
            logs.append(f"Container Exception: {e}")
            # raise # Do not raise, return error log
            return -1, "\n".join(logs)
            
        finally:
            # We use the helper method again in finally
            self._cleanup_container(container_name)
            
        return exit_code, "\n".join(logs)

    def _cleanup_container(self, container_name):
        """
        Removes the container if it exists.
        """
        try:
            # Check if container exists
            try:
                old_container = self.client.containers.get(container_name)
                logger.info(f"Removing existing container '{container_name}'...")
                old_container.remove(force=True)
            except docker.errors.NotFound:
                pass
        except Exception as e:
            logger.warning(f"Failed to cleanup container '{container_name}': {e}")

    def _extract_artifacts(self, output_path: str):
        """
        Copies the compiled artifacts (classes/jars) to the output directory.
        """
        logger.info("Extracting artifacts...")
        
        # Source: workspace/path/to/build/target/classes (Maven) or build/classes/java/main (Gradle)
        source_classes_mvn = os.path.join(self.workspace_path, self.build_relative_path, "target", "classes")
        source_classes_gradle = os.path.join(self.workspace_path, self.build_relative_path, "build", "classes", "java", "main")
        
        source_classes = None
        if os.path.exists(source_classes_mvn):
            source_classes = source_classes_mvn
        elif os.path.exists(source_classes_gradle):
            source_classes = source_classes_gradle
        else:
            # Fallback check for older Gradle structure or other variants
            source_classes_gradle_legacy = os.path.join(self.workspace_path, self.build_relative_path, "build", "classes", "main")
            if os.path.exists(source_classes_gradle_legacy):
                source_classes = source_classes_gradle_legacy

        if not source_classes:
            logger.warning(f"No classes found at {source_classes_mvn} or {source_classes_gradle}")
            return
            
        # Destination: output/classes
        dest_classes = os.path.join(output_path, "classes")
        
        if os.path.exists(dest_classes):
            shutil.rmtree(dest_classes)
            
        try:
            shutil.copytree(source_classes, dest_classes)
            logger.info(f"Artifacts extracted to {dest_classes}")
        except Exception as e:
            logger.error(f"Failed to extract artifacts: {e}")
