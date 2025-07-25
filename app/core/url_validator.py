# app/utils/url_validator.py
import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple, Optional
import re


class URLSecurityValidator:
    """
    Validates URLs to prevent monitoring of private/internal resources.
    Blocks localhost, private IPs, and internal network access.
    """
    
    # Private IP ranges (RFC 1918, RFC 4193, etc.)
    PRIVATE_IP_RANGES = [
        ipaddress.ip_network('10.0.0.0/8'),      # Private Class A
        ipaddress.ip_network('172.16.0.0/12'),   # Private Class B  
        ipaddress.ip_network('192.168.0.0/16'),  # Private Class C
        ipaddress.ip_network('127.0.0.0/8'),     # Loopback
        ipaddress.ip_network('169.254.0.0/16'),  # Link-local
        ipaddress.ip_network('224.0.0.0/4'),     # Multicast
        ipaddress.ip_network('::1/128'),         # IPv6 loopback
        ipaddress.ip_network('fc00::/7'),        # IPv6 private
        ipaddress.ip_network('fe80::/10'),       # IPv6 link-local
    ]
    
    # Blocked hostnames/domains
    BLOCKED_HOSTNAMES = {
        'localhost',
        '0.0.0.0',
        'broadcasthost',
        'local',
        'internal',
        'intranet',
        'corp',
        'lan',
    }
    
    # Blocked TLDs that are typically internal
    BLOCKED_TLDS = {
        '.local', '.internal', '.intranet', '.corp', '.lan', '.home'
    }

    @classmethod
    def validate_url(cls, url: str) -> Tuple[bool, Optional[str]]:
        """
        Validate if URL is safe for external monitoring.
        
        Returns:
            (is_valid, error_message)
        """
        try:
            # Basic URL parsing
            if not url or not isinstance(url, str):
                return False, "URL is required and must be a string"
            
            # Ensure URL has a scheme
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            parsed = urlparse(url)
            
            if not parsed.hostname:
                return False, "Invalid URL format"
            
            hostname = parsed.hostname.lower()
            
            # Check blocked hostnames
            if hostname in cls.BLOCKED_HOSTNAMES:
                return False, f"Monitoring '{hostname}' is not allowed for security reasons"
            
            # Check blocked TLD patterns
            for blocked_tld in cls.BLOCKED_TLDS:
                if hostname.endswith(blocked_tld):
                    return False, f"Monitoring '{blocked_tld}' domains is not allowed"
            
            # Check for localhost patterns
            if cls._is_localhost_pattern(hostname):
                return False, "Localhost URLs are not allowed for monitoring"
            
            # Resolve hostname to IP and check if it's private
            try:
                ip_address = socket.gethostbyname(hostname)
                if cls._is_private_ip(ip_address):
                    return False, f"Private IP addresses ({ip_address}) are not allowed for monitoring"
            except socket.gaierror:
                # If we can't resolve, it might be invalid but let it through
                # The actual HTTP request will fail naturally
                pass
            
            # Check port restrictions
            port = parsed.port
            if port and not cls._is_allowed_port(port):
                return False, f"Port {port} is not allowed for monitoring"
            
            return True, None
            
        except Exception as e:
            return False, f"URL validation error: {str(e)}"
    
    @classmethod
    def _is_localhost_pattern(cls, hostname: str) -> bool:
        """Check if hostname matches localhost patterns."""
        localhost_patterns = [
            r'^localhost$',
            r'^127\.',
            r'^0\.0\.0\.0$',
            r'.*\.localhost$',
            r'.*\.local$',
        ]
        
        for pattern in localhost_patterns:
            if re.match(pattern, hostname):
                return True
        return False
    
    @classmethod
    def _is_private_ip(cls, ip_string: str) -> bool:
        """Check if IP address is in private ranges."""
        try:
            ip = ipaddress.ip_address(ip_string)
            return any(ip in network for network in cls.PRIVATE_IP_RANGES)
        except (ipaddress.AddressValueError, ValueError):
            return False
    
    @classmethod
    def _is_allowed_port(cls, port: int) -> bool:
        """Check if port is allowed for monitoring."""
        # Block common internal/admin ports
        blocked_ports = {
            22,    # SSH
            23,    # Telnet
            25,    # SMTP
            53,    # DNS
            110,   # POP3
            143,   # IMAP
            993,   # IMAPS
            995,   # POP3S
            1433,  # SQL Server
            1521,  # Oracle
            3306,  # MySQL
            3389,  # RDP
            5432,  # PostgreSQL
            5984,  # CouchDB
            6379,  # Redis
            9200,  # Elasticsearch
            27017, # MongoDB
        }
        
        # Allow common web ports
        allowed_ports = {80, 443, 8080, 8443, 3000, 3001, 4000, 5000, 8000, 8888, 9000}
        
        if port in allowed_ports:
            return True
        
        if port in blocked_ports:
            return False
        
        # Allow high ports (usually safe)
        if port >= 8000:
            return True
        
        return False


def validate_monitoring_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate a URL for monitoring.
    
    Args:
        url: URL to validate
        
    Returns:
        (is_valid, error_message)
    """
    return URLSecurityValidator.validate_url(url)