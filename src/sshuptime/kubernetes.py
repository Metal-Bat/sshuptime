"""Asynchronous Kubernetes runtime strategy."""

import asyncio
import os
from pathlib import Path

from .config import SourceSettings
from .models import Resource
from .presentation import runtime_views
from .source_utils import log_tail, safe_json


class KubernetesCollector:
    """Read cluster inventory with the asynchronous Kubernetes client."""

    name = "Kubernetes"

    def __init__(
        self,
        kubeconfig: str | None = None,
        context: str | None = None,
        settings: SourceSettings | None = None,
    ) -> None:
        self.settings = settings or SourceSettings()
        self.views = runtime_views("Pods", "Nodes", "Services")
        self.kubeconfig = kubeconfig or self.settings.kubeconfig
        self.context = context or self.settings.kube_context

    async def collect(self) -> dict[str, list[Resource]] | None:
        """List cluster resources and isolate per-kind permission failures."""
        from kubernetes_asyncio import client, config

        incluster = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
        kubeconfig = (
            self.kubeconfig
            or os.environ.get("KUBECONFIG")
            or str(Path.home() / ".kube/config")
        )
        if not incluster and not Path(kubeconfig).is_file():
            return None
        if incluster and not self.kubeconfig:
            config.load_incluster_config()
        else:
            await config.load_kube_config(config_file=kubeconfig, context=self.context)
        async with client.ApiClient() as api_client:
            api = client.CoreV1Api(api_client)
            pods, nodes, services = await asyncio.gather(
                api.list_pod_for_all_namespaces(
                    _request_timeout=self.settings.request_timeout
                ),
                api.list_node(_request_timeout=self.settings.request_timeout),
                api.list_service_for_all_namespaces(
                    _request_timeout=self.settings.request_timeout
                ),
                return_exceptions=True,
            )
            if (
                isinstance(pods, BaseException)
                and isinstance(nodes, BaseException)
                and isinstance(services, BaseException)
            ):
                raise pods
            pod_rows = []
            for index, pod in enumerate(
                pods.items if not isinstance(pods, BaseException) else []
            ):
                status = pod.status
                states = list(status.container_statuses or []) if status else []
                waiting = [
                    s.state.waiting.reason
                    for s in states
                    if s.state and s.state.waiting
                ]
                state = (
                    "crashed"
                    if any(
                        x in {"CrashLoopBackOff", "Error", "ImagePullBackOff"}
                        for x in waiting
                    )
                    else "running"
                    if status and status.phase == "Running"
                    else (
                        status.phase.lower() if status and status.phase else "unknown"
                    )
                )
                namespace = pod.metadata.namespace
                name = pod.metadata.name
                logs = []
                if index < self.settings.max_log_items or state in {
                    "crashed",
                    "failed",
                }:
                    try:
                        logs = log_tail(
                            await api.read_namespaced_pod_log(
                                name,
                                namespace,
                                tail_lines=self.settings.log_lines,
                                timestamps=True,
                                _request_timeout=self.settings.request_timeout,
                            ),
                            lines=self.settings.log_lines,
                            max_bytes=self.settings.log_bytes,
                        )
                    except Exception:  # noqa: BLE001,S110 - pods may disappear or deny log access  # nosec B110
                        pass
                pod_rows.append(
                    Resource(
                        id=pod.metadata.uid or f"{namespace}/{name}",
                        name=name,
                        state=state,
                        info=f"{namespace} · {pod.spec.node_name or 'unscheduled'}",
                        manifest=safe_json(api_client.sanitize_for_serialization(pod)),
                        logs=logs,
                    )
                )
            node_rows = []
            for node in nodes.items if not isinstance(nodes, BaseException) else []:
                ready = next(
                    (
                        condition.status
                        for condition in node.status.conditions or []
                        if condition.type == "Ready"
                    ),
                    None,
                )
                node_rows.append(
                    Resource(
                        id=node.metadata.uid or node.metadata.name,
                        name=node.metadata.name,
                        state="ready" if ready == "True" else "notready",
                        info=str(
                            node.status.node_info.os_image
                            if node.status.node_info
                            else ""
                        ),
                        manifest=safe_json(api_client.sanitize_for_serialization(node)),
                    )
                )
            service_rows = [
                Resource(
                    id=s.metadata.uid or f"{s.metadata.namespace}/{s.metadata.name}",
                    name=s.metadata.name,
                    state="active",
                    info=f"{s.metadata.namespace} · {s.spec.type}",
                    manifest=safe_json(api_client.sanitize_for_serialization(s)),
                )
                for s in (
                    services.items if not isinstance(services, BaseException) else []
                )
            ]
            for title, result, rows in (
                ("Pods", pods, pod_rows),
                ("Nodes", nodes, node_rows),
                ("Services", services, service_rows),
            ):
                if isinstance(result, BaseException):
                    rows.append(
                        Resource(
                            id=f"{title.lower()}-unavailable",
                            name=f"{title} unavailable",
                            state="error",
                            info=str(result)[:160],
                            manifest={
                                "error": type(result).__name__,
                                "message": str(result)[:500],
                            },
                        )
                    )
            return {"Pods": pod_rows, "Nodes": node_rows, "Services": service_rows}
