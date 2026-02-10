import os
import socket
import logging
import uuid
import requests
import time
import threading
from typing import List, Optional, Dict

# Configure simplified logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("service-discovery")


class ServiceDiscovery:
    """Consul-based service discovery for microservices."""

    def __init__(self, service_name: str, port: int, service_id: Optional[str] = None, tags: Optional[List[str]] = None):
        """
        Initialize Service Discovery.

        Args:
            service_name: Name of the service (e.g., 'lily-discord-adapter')
            port: Port the service is running on
            service_id: Unique ID (defaults to service_name-hostname-uuid)
            tags: List of tags (e.g., ['discord', 'adapter'])
        """
        self.consul_host = os.getenv("CONSUL_HTTP_ADDR", "consul:8500")
        # Ensure we have a clean host/port for requests
        if "://" not in self.consul_host:
            self.consul_url = f"http://{self.consul_host}"
        else:
            self.consul_url = self.consul_host

        self.service_name = service_name
        self.port = port
        self.hostname = socket.gethostname()  # Docker container ID usually

        # Create a unique ID if not provided
        self.service_id = service_id or f"{service_name}-{self.hostname}-{uuid.uuid4().hex[:8]}"
        self.tags = tags or []
        
        # Add public URL tag if DOMAIN_NAME is set
        domain_name = os.getenv("DOMAIN_NAME")
        if domain_name:
            # Construct hostname: {service_name}.{domain_name}
            hostname = f"{service_name}.{domain_name}"
            self.tags.append(f"hostname={hostname}")

        # Registration thread control
        self._stop_event = threading.Event()
        self._registration_thread = None

    def register(self):
        """
        Register service with Consul.
        If it fails, it will NOT retry automatically here. Use start() for robust behavior.
        """
        url = f"{self.consul_url}/v1/agent/service/register"

        # Define health check (assuming the service has a /health endpoint)
        check = {
            "HTTP": f"http://{self.hostname}:{self.port}/health",
            "Interval": "10s",
            "Timeout": "2s",
            "DeregisterCriticalServiceAfter": "1m"
        }

        payload = {
            "ID": self.service_id,
            "Name": self.service_name,
            "Tags": self.tags,
            "Address": self.hostname,
            "Port": self.port,
            "Check": check
        }

        try:
            logger.info(f"Attempting to register {self.service_name} ({self.service_id}) with Consul at {self.consul_url}...")
            response = requests.put(url, json=payload, timeout=5)
            response.raise_for_status()
            logger.info(f"Successfully registered {self.service_name} with Consul.")
            return True
        except Exception as e:
            logger.error(f"Failed to register with Consul: {e}")
            return False

    def deregister(self):
        """Deregister the service."""
        if self._registration_thread and self._registration_thread.is_alive():
            self._stop_event.set()
            self._registration_thread.join(timeout=1.0)

        url = f"{self.consul_url}/v1/agent/service/deregister/{self.service_id}"
        try:
            requests.put(url, timeout=2)
            logger.info(f"Deregistered {self.service_name}.")
        except Exception as e:
            logger.error(f"Failed to deregister: {e}")

    def start(self):
        """Start a background thread to ensure registration succeeds (retry logic)."""
        self._stop_event.clear()
        self._registration_thread = threading.Thread(target=self._maintain_registration, daemon=True)
        self._registration_thread.start()

    def _maintain_registration(self):
        """Retry registration until success, then monitor."""
        while not self._stop_event.is_set():
            if self.register():
                # If success, we are good. Consul will Health Check us.
                break

            # Wait before retrying
            logger.info("Retrying registration in 5 seconds...")
            self._stop_event.wait(5.0)

    # ==================== SERVICE DISCOVERY METHODS ====================

    def get_services(self, service_name: Optional[str] = None) -> List[Dict]:
        """
        Get all registered services or filter by service name.

        Args:
            service_name: Optional filter for specific service

        Returns:
            List of service dictionaries with address, port, health status
        """
        url = f"{self.consul_url}/v1/health/service"
        if service_name:
            url = f"{url}/{service_name}?passing=true"
        else:
            url = f"{url}?passing=true"

        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            services = response.json()

            result = []
            for svc in services:
                service_info = svc.get("Service", {})
                checks = svc.get("Checks", [])

                # Determine health status
                health = "passing"
                for check in checks:
                    if check.get("Status") != "passing":
                        health = "critical"
                        break

                result.append({
                    "id": service_info.get("ID"),
                    "name": service_info.get("Service"),
                    "address": service_info.get("Address"),
                    "port": service_info.get("Port"),
                    "tags": service_info.get("Tags", []),
                    "health": health
                })

            logger.debug(f"Discovered {len(result)} services")
            return result

        except Exception as e:
            logger.error(f"Failed to discover services: {e}")
            return []

    def get_service_url(self, service_name: str, protocol: str = "http") -> Optional[str]:
        """
        Get the URL for a service based on protocol.

        Args:
            service_name: Name of the service to find
            protocol: Protocol (http, ws)

        Returns:
            URL string (e.g., https://hostname/api or wss://hostname/ws)
        """
        services = self.get_services(service_name)
        
        if services:
            svc = services[0]
            hostname = None
            
            # Extract hostname from tags
            for tag in svc.get('tags', []):
                if tag.startswith('hostname='):
                    hostname = tag.split('=', 1)[1]
                    break
            
            if hostname:
                # Always use HTTPS/WSS for secure communication
                if protocol == 'http':
                    protocol = 'https'
                elif protocol == 'ws':
                    protocol = 'wss'
                
                base_url = f"{protocol}://{hostname}"

                if protocol == 'wss':
                    return f"{base_url}/ws"
                return f"{base_url}/api"
            
        return None

    def discover_all_services(self) -> Dict[str, List[Dict]]:
        """
        Discover all registered services grouped by name.

        Returns:
            Dictionary with service names as keys and lists of service instances as values
        """
        all_services = self.get_services()
        grouped = {}

        for svc in all_services:
            name = svc["name"]
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(svc)

        return grouped
