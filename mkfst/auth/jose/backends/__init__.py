from .base import DIRKey  # noqa: F401
from .native import get_random_bytes  # noqa: F401

try:
    from .cryptography_backend import CryptographyRSAKey as RSAKey  # noqa: F401
except ImportError:  # pragma: no cover
    try:
        from .rsa_backend import RSAKey  # noqa: F401
    except ImportError:
        RSAKey = None

try:
    from .cryptography_backend import CryptographyECKey as ECKey  # noqa: F401
except ImportError:  # pragma: no cover
    from .ecdsa_backend import ECDSAECKey as ECKey  # noqa: F401

try:
    from .cryptography_backend import CryptographyAESKey as AESKey  # noqa: F401
except ImportError:  # pragma: no cover
    AESKey = None

try:
    from .cryptography_backend import CryptographyHMACKey as HMACKey  # noqa: F401
except ImportError:  # pragma: no cover
    from .native import HMACKey  # noqa: F401
