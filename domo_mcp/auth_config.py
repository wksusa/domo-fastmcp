"""Re-export shared auth factory (implementation lives in wks-mcp-auth)."""

from mcp_auth.auth_config import create_auth, detect_jwt_algorithm

# Backward compatibility for tests importing private name
_detect_algorithm = detect_jwt_algorithm

__all__ = ["create_auth", "detect_jwt_algorithm", "_detect_algorithm"]
