"""Docker Compose execution engine.

Provides type-safe execution of compose lifecycle commands (up, down, pull, build, config)
with custom project name injection, Doppler variable support, and execution metrics.
"""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from orchestrator.core.guards import is_test_environment
from orchestrator.core.models import ExecutionResult, ServiceMetadata

logger = logging.getLogger(__name__)


class ComposeEngine:
    """Type-safe wrapper for Docker Compose v2 commands."""

    def __init__(self, default_timeout: int = 300):
        self.default_timeout = default_timeout

    def build_compose_cmd(
        self,
        service: ServiceMetadata,
        subcommand: list[str],
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
    ) -> list[str]:
        """Construct the base docker compose command with project and file arguments."""
        cmd = ["docker", "compose"]
        if service.project_name:
            cmd.extend(["-p", service.project_name])
        cmd.extend(["-f", service.compose_file])
        cmd.extend(subcommand)
        if cmd_wrapper:
            cmd = cmd_wrapper(cmd)
        return cmd

    def compose_up(
        self,
        service: ServiceMetadata,
        recreate: bool = False,
        build: bool = False,
        pull: bool = False,
        detach: bool = True,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute 'docker compose up' for the given service."""
        subcmd = ["up"]
        if detach:
            subcmd.append("-d")
        if pull and not service.is_local_build:
            subcmd.extend(["--pull", "always"])
        if recreate:
            subcmd.extend(["--force-recreate", "--renew-anon-volumes"])
        if build:
            subcmd.append("--build")
        subcmd.append("--remove-orphans")

        cmd = self.build_compose_cmd(service, subcmd, cmd_wrapper=cmd_wrapper)
        return self._run_command(
            service=service,
            action="compose_up",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=timeout or self.default_timeout,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def compose_down(
        self,
        service: ServiceMetadata,
        remove_orphans: bool = True,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute 'docker compose down' for the given service."""
        subcmd = ["down"]
        if remove_orphans:
            subcmd.append("--remove-orphans")

        cmd = self.build_compose_cmd(service, subcmd, cmd_wrapper=cmd_wrapper)
        return self._run_command(
            service=service,
            action="compose_down",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=timeout or 60,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def compose_pull(
        self,
        service: ServiceMetadata,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute 'docker compose pull' for the given service."""
        if service.is_local_build:
            logger.info("[INFO] Skipping registry pull for local build '%s'", service.name)
            return ExecutionResult(
                service=service,
                action="compose_pull",
                success=True,
                exit_code=0,
                message=f"Skipped pull for local build '{service.name}'.",
            )
        cmd = self.build_compose_cmd(service, ["pull", "-q"], cmd_wrapper=cmd_wrapper)
        return self._run_command(
            service=service,
            action="compose_pull",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=timeout or self.default_timeout,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def compose_build(
        self,
        service: ServiceMetadata,
        no_cache: bool = False,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute 'docker compose build' for the given service."""
        subcmd = ["build"]
        if no_cache:
            subcmd.append("--no-cache")

        cmd = self.build_compose_cmd(service, subcmd, cmd_wrapper=cmd_wrapper)
        return self._run_command(
            service=service,
            action="compose_build",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=timeout or self.default_timeout,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def compose_config(
        self,
        service: ServiceMetadata,
        quiet: bool = True,
        env: Optional[dict[str, str]] = None,
        cmd_wrapper: Optional[Callable[[list[str]], list[str]]] = None,
    ) -> tuple[bool, str]:
        """Validate compose file syntax via 'docker compose config'."""
        subcmd = ["config"]
        if quiet:
            subcmd.append("-q")

        cmd = self.build_compose_cmd(service, subcmd, cmd_wrapper=cmd_wrapper)
        res = self._run_command(
            service=service,
            action="compose_config",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=30,
            stream_output=False,
        )
        return res.success, res.message

    def compose_stop(
        self,
        service: ServiceMetadata,
        timeout: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute 'docker compose stop' for the given service."""
        cmd = self.build_compose_cmd(service, ["stop"])
        return self._run_command(
            service=service,
            action="compose_stop",
            cmd=cmd,
            cwd=service.abs_dir,
            env=env,
            timeout=timeout or 60,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def stop_by_ids(
        self,
        service: ServiceMetadata,
        container_ids: list[str],
        timeout: int = 30,
        stream_output: bool = False,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Stop containers directly by ID, bypassing compose file env interpolation.

        Uses 'docker stop <id...>' which needs no compose file parsing and therefore
        works without Doppler secrets being present in the shell. This is the correct
        stop path for services with required env vars in their compose definitions.
        """
        if not container_ids:
            return ExecutionResult(
                service=service,
                action="stop_by_ids",
                success=True,
                exit_code=0,
                message="No container IDs provided.",
            )
        cmd = ["docker", "stop", f"--timeout={timeout}"] + container_ids
        return self._run_command(
            service=service,
            action="stop_by_ids",
            cmd=cmd,
            cwd=service.abs_dir,
            timeout=timeout + 5,
            stream_output=stream_output,
            stream_mode=stream_mode,
        )

    def stop(
        self,
        service: ServiceMetadata,
        timeout: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
        stream_output: bool = True,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Convenience alias for compose_stop."""
        return self.compose_stop(service, timeout=timeout, env=env, stream_output=stream_output, stream_mode=stream_mode)

    def compose_ps(
        self,
        service: ServiceMetadata,
        quiet: bool = True,
        env: Optional[dict[str, str]] = None,
    ) -> list[str]:
        """Return list of running container IDs for this compose project.

        Uses 'docker ps --filter label=com.docker.compose.project=<name>' instead of
        'docker compose ps' to avoid requiring Doppler env var injection just for a
        liveness check. Docker attaches the project label at startup, so this works
        regardless of whether compose file env vars are currently set.
        """
        raw_candidates = []
        if service.custom_project_name:
            raw_candidates.append(service.custom_project_name)
        raw_candidates.append(service.abs_dir.name)
        raw_candidates.append(service.name)

        projects_to_check: list[str] = []
        for cand in raw_candidates:
            if cand and cand not in projects_to_check:
                projects_to_check.append(cand)
            if cand and cand.lower() not in projects_to_check:
                projects_to_check.append(cand.lower())

        found_cids: list[str] = []
        for project in projects_to_check:
            cmd = [
                "docker", "ps", "-q",
                "--filter", f"label=com.docker.compose.project={project}",
            ]
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for cid in result.stdout.splitlines():
                        clean_cid = cid.strip()
                        if clean_cid and clean_cid not in found_cids:
                            found_cids.append(clean_cid)
            except Exception as e:
                logger.debug("docker ps label filter failed for %s (project %s): %s", service.name, project, e)
        return found_cids

    def ps(
        self,
        service: ServiceMetadata,
        quiet: bool = True,
        env: Optional[dict[str, str]] = None,
    ) -> list[str]:
        """Convenience alias for compose_ps."""
        return self.compose_ps(service, quiet=quiet, env=env)

    def is_project_active(
        self,
        service: ServiceMetadata,
        env: Optional[dict[str, str]] = None,
    ) -> bool:
        """Check if any containers belonging to this compose project are running."""
        running_cids = self.compose_ps(service, quiet=True, env=env)
        return len(running_cids) > 0

    def _run_command(
        self,
        service: Optional[ServiceMetadata],
        action: str,
        cmd: list[str],
        cwd: Path,
        env: Optional[dict[str, str]] = None,
        timeout: int = 300,
        stream_output: bool = False,
        stream_mode: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a subprocess command with timing and error capture."""
        start_time = time.monotonic()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        from orchestrator.core.state import get_log_stream_mode

        should_stream = stream_output and not is_test_environment()
        vps_ctx = service.vps if service else None
        mode = (stream_mode or get_log_stream_mode(vps=vps_ctx)).lower() if should_stream else "quiet"

        try:
            if should_stream:
                if mode == "native":
                    process = subprocess.run(
                        cmd,
                        cwd=str(cwd),
                        env=merged_env,
                        timeout=timeout,
                    )
                    duration = round(time.monotonic() - start_time, 2)
                    success = process.returncode == 0
                    if not success:
                        logger.debug("Compose %s returned exit code %d for %s", action, process.returncode, service.name if service else cwd)

                    return ExecutionResult(
                        service=service,
                        action=action,
                        success=success,
                        exit_code=process.returncode,
                        message="Command executed with live terminal output" if success else f"Command failed with exit code {process.returncode}",
                        duration_seconds=duration,
                    )
                elif mode == "piped":
                    import sys

                    collected_lines: list[str] = []
                    process = subprocess.Popen(
                        cmd,
                        cwd=str(cwd),
                        env=merged_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    if process.stdout:
                        for line in iter(process.stdout.readline, ""):
                            sys.stdout.write(line)
                            sys.stdout.flush()
                            collected_lines.append(line)
                        process.stdout.close()
                    returncode = process.wait(timeout=timeout)
                    duration = round(time.monotonic() - start_time, 2)
                    msg = "".join(collected_lines).strip()
                    success = returncode == 0
                    if not success and msg:
                        logger.debug("Compose %s returned exit code %d for %s", action, returncode, service.name if service else cwd)

                    return ExecutionResult(
                        service=service,
                        action=action,
                        success=success,
                        exit_code=returncode,
                        message=msg,
                        duration_seconds=duration,
                    )

            process = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            duration = round(time.monotonic() - start_time, 2)
            success = process.returncode == 0
            msg = process.stdout.strip() if success else (process.stderr.strip() or process.stdout.strip())
            if not success and msg:
                if action in ("compose_up", "compose_down", "compose_stop", "compose_build", "compose_pull"):
                    logger.error("[ERROR] Compose %s failed for %s:\n%s", action, service.name if service else cwd, msg)
                else:
                    logger.debug("Compose %s inspection returned non-zero for %s: %s", action, service.name if service else cwd, msg)

            return ExecutionResult(
                service=service,
                action=action,
                success=success,
                exit_code=process.returncode,
                message=msg,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            duration = round(time.monotonic() - start_time, 2)
            return ExecutionResult(
                service=service,
                action=action,
                success=False,
                exit_code=124,
                message=f"Command timed out after {timeout}s: {' '.join(cmd)}",
                duration_seconds=duration,
            )
        except Exception as e:
            duration = round(time.monotonic() - start_time, 2)
            return ExecutionResult(
                service=service,
                action=action,
                success=False,
                exit_code=1,
                message=str(e),
                duration_seconds=duration,
            )


default_compose_engine = ComposeEngine()
