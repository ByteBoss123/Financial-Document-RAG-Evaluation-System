import hashlib
import hmac

def verify_password(password,expected_sha256):
    if not expected_sha256 or len(expected_sha256)!=64:
        return False
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(),expected_sha256.lower())
